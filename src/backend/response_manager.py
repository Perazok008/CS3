import json
import os
import re
import signal

from huggingface_hub import InferenceClient
import prometheus_client as pc

LOCAL_TIMEOUT = 90


class _InferenceTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _InferenceTimeout("Local model inference timed out")

from config import API_MODEL, LOCAL_MODEL, MEMORY_START, MEMORY_END, PERSONALITIES
from schemas import ChatRequest, ChatResponse
from memory_manager import get_personality_memory, save_personality_memory

BACKEND_MODEL_EMPTY_RESPONSES_TOTAL = pc.Counter(
    'backend_model_empty_responses_total',
    'Count of empty LLM responses (first attempt or retry).',
    ['backend']
)

BACKEND_MEMORY_PARSE_FAILURES_TOTAL = pc.Counter(
    'backend_memory_parse_failures_total',
    'Count of JSON extraction failures requiring fallback regex in split_response.',
)

BACKEND_MEMORY_ITEMS_SAVED_TOTAL = pc.Counter(
    'backend_memory_items_saved_total',
    'Count of memory items persisted, by personality.',
    ['personality']
)

_HF_TOKEN = os.environ.get("HF_TOKEN", "")

_local_pipe = None

def _get_local_pipe():
    global _local_pipe
    if _local_pipe is None:
        from transformers import pipeline
        _local_pipe = pipeline("text-generation", model=LOCAL_MODEL)
    return _local_pipe


def _normalize_messages(messages):
    """Ensure every message content is a plain string (local pipeline requirement)."""
    normalized = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        normalized.append({"role": msg["role"], "content": str(content)})
    return normalized


def chat_completion(messages, max_tokens, temperature, top_p, use_local=False):
    """Send messages to either the local model or HF Inference API and return the response text."""
    if use_local:
        local_messages = _normalize_messages(messages)
        prev = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(LOCAL_TIMEOUT)
        try:
            outputs = _get_local_pipe()(
                local_messages,
                max_new_tokens=max_tokens,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
            )
            content = outputs[0]["generated_text"][-1]["content"]
            if not content:
                BACKEND_MODEL_EMPTY_RESPONSES_TOTAL.labels(backend="local").inc()
                print("[LOCAL] Empty response, retrying once...")
                outputs = _get_local_pipe()(
                    local_messages,
                    max_new_tokens=max_tokens,
                    do_sample=True,
                    temperature=temperature,
                    top_p=top_p,
                )
                content = outputs[0]["generated_text"][-1]["content"]
                if not content:
                    BACKEND_MODEL_EMPTY_RESPONSES_TOTAL.labels(backend="local").inc()
                    print("[LOCAL] Retry also returned empty content")
        except _InferenceTimeout:
            BACKEND_MODEL_EMPTY_RESPONSES_TOTAL.labels(backend="local").inc()
            print("[LOCAL] Inference timed out after {LOCAL_TIMEOUT}s")
            content = ""
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, prev)
        return content or ""

    client = InferenceClient(model=API_MODEL, token=_HF_TOKEN)
    response = client.chat_completion(
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        tool_choice="none",
    )
    content = response.choices[0].message.content
    if not content:
        BACKEND_MODEL_EMPTY_RESPONSES_TOTAL.labels(backend="api").inc()
        print("[API] Empty response, retrying once...")
        response = client.chat_completion(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            tool_choice="none",
        )
        content = response.choices[0].message.content
        if not content:
            BACKEND_MODEL_EMPTY_RESPONSES_TOTAL.labels(backend="api").inc()
            print("[API] Retry also returned empty content")
    return content or ""


_MEMORY_RE = re.compile(
    rf"(?s)(.*?){re.escape(MEMORY_START)}\s*(.*?)\s*{re.escape(MEMORY_END)}",
)

# Fallback: find a JSON object containing "write_memory" when delimiters are missing
_FALLBACK_RE = re.compile(r'(?s)\{[^{}]*"write_memory"[^{}]*\{.*?\}[^{}]*\}')


def split_response(raw_text):
    """ Separate response text into chat text and memory JSON data. """
    if not raw_text:
        print("[PARSE] Received empty response text")
        return "", {}

    # Primary: use delimiters
    m = _MEMORY_RE.search(raw_text)
    if m:
        chat_text = m.group(1).strip()
        json_text = m.group(2).strip()
        try:
            memory_data = json.loads(json_text)
            return chat_text, memory_data
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[PARSE] JSON decode error between delimiters: {e}")
            return chat_text, {}

    # Fallback: try to find a JSON object with "write_memory" key (for weaker models)
    # A bit of anightmare, but it's the best we can do to stabilize the local model responses.
    BACKEND_MEMORY_PARSE_FAILURES_TOTAL.inc()
    print("[PARSE] No memory delimiters found, trying fallback JSON extraction")
    print(f"[PARSE] Raw response (last 300 chars): ...{raw_text[-300:]}")

    wm_idx = raw_text.find('"write_memory"')
    if wm_idx != -1:
        # Walk backwards to find the opening brace
        start = raw_text.rfind("{", 0, wm_idx)
        if start != -1:
            # Brace-count forward to find matching close
            depth = 0
            for i in range(start, len(raw_text)):
                if raw_text[i] == "{":
                    depth += 1
                elif raw_text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        json_text = raw_text[start:i + 1]
                        try:
                            memory_data = json.loads(json_text)
                            chat_text = raw_text[:start].strip()
                            print(f"[PARSE] Fallback extracted JSON successfully")
                            return chat_text, memory_data
                        except (json.JSONDecodeError, TypeError) as e:
                            print(f"[PARSE] Fallback JSON decode error: {e}")
                            break
            else:
                print("[PARSE] Fallback: unbalanced braces, could not extract JSON")

    print("[PARSE] No memory JSON found in response")
    return raw_text.strip(), {}


def extract_memory_items(data):
    """ Validate and extract memory items from parsed JSON. """
    if not isinstance(data, dict):
        if data:
            print(f"[MEMORY] Expected dict but got {type(data).__name__}, skipping memory extraction")
        return []
    items = []
    for item in data.get("items", []):
        if not isinstance(item, dict):
            print(f"[MEMORY] Skipping non-dict item: {item!r}")
            continue
        note = str(item.get("note", "")).strip()
        if not note:
            print(f"[MEMORY] Skipping item with empty note (label: {item.get('label', '?')})")
            continue
        try:
            importance = int(item.get("importance", 1))
        except (TypeError, ValueError):
            print(f"[MEMORY] Invalid importance '{item.get('importance')}' for '{note}', defaulting to 1")
            importance = 1
        items.append({
            "label": str(item.get("label", "")).strip(),
            "note": note,
            "importance": importance,
        })
    if items:
        print(f"[MEMORY] Extracted {len(items)} new memory item(s)")
    return items


def respond(request: ChatRequest) -> ChatResponse:
    """Process a chat request: build context, call the model, persist memory."""
    message = request.message
    history = [m.model_dump() for m in request.history]
    personality = request.personality
    system_message = PERSONALITIES[personality]["system_prompt"]
    max_tokens = request.settings.max_tokens
    temperature = request.settings.temperature
    top_p = request.settings.top_p
    min_recall_importance = request.settings.min_recall_importance
    min_save_importance = request.settings.min_save_importance
    recent_turns = request.settings.recent_turns
    user_id = request.session_id
    current_memory = get_personality_memory(user_id, personality)

    # Build messages list
    messages = [{"role": "system", "content": system_message}]

    # Inject memory context for items at or above the recall importance threshold
    recall_threshold = int(min_recall_importance)
    # Including importance score in prompt messes up responses, so sort instead
    relevant = sorted(
        [m for m in current_memory if m.get("importance", 0) >= recall_threshold],
        key=lambda m: m.get("importance", 0),
        reverse=True,
    )
    if relevant:
        print(f"[MEMORY] Injecting {len(relevant)} memory item(s) (importance >= {recall_threshold})")
        lines = [f"- [{m['label']}] {m['note']}" for m in relevant]
        # More predictable when sent from user
        messages.append({"role": "user", "content": "Known facts about me:\n" + "\n".join(lines)})

    # Append recent conversation history
    max_msgs = int(recent_turns) * 2
    messages.extend(history[-max_msgs:])

    # Append new user message
    messages.append({"role": "user", "content": message})

    raw = chat_completion(messages, max_tokens, temperature, top_p, request.use_local)

    chat_text, data = split_response(raw)
    new_items = extract_memory_items(data)

    # Ensure we never send an empty message to the chat
    if not chat_text:
        print("[WARN] Model returned empty chat text, sending fallback")
        chat_text = "Error: the model returned an empty response. Please try again."

    # Filter new items by save importance threshold before persisting
    save_threshold = int(min_save_importance)
    saved_items = [item for item in new_items if item["importance"] >= save_threshold]
    if len(saved_items) < len(new_items):
        dropped = len(new_items) - len(saved_items)
        print(f"[MEMORY] Dropped {dropped} item(s) below save threshold (importance < {save_threshold})")

    # Append new items to existing memory and persist
    if saved_items:
        BACKEND_MEMORY_ITEMS_SAVED_TOTAL.labels(personality=personality).inc(len(saved_items))
    current_memory.extend(saved_items)
    save_personality_memory(user_id, personality, current_memory)

    return ChatResponse(response=chat_text, memory_items=current_memory)
