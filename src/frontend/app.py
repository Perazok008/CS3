import os
import uuid
import prometheus_client as pc
from time import perf_counter
import gradio as gr

from SettingsSidebar import SettingsSidebar
import api

PERSONALITIES = api.get_personalities()
DEFAULT_PERSONALITY = PERSONALITIES[0]

FRONTEND_CHAT_REQUESTS_TOTAL = pc.Counter(
    'frontend_chat_requests_total',
    'Total chat requests from the UI.',
)

FRONTEND_CHAT_ERRORS_TOTAL = pc.Counter(
    'frontend_chat_errors_total',
    'Total chat errors by type.',
    ['error_type']
)

FRONTEND_CHAT_DURATION_SECONDS = pc.Histogram(
    'frontend_chat_duration_seconds',
    'End-to-end duration from user click to response.',
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 120],
)

FRONTEND_PERSONALITY_SWITCHES_TOTAL = pc.Counter(
    'frontend_personality_switches_total',
    'Personality switch events by personality.',
    ['personality']
)

FRONTEND_LOCAL_MODEL_TOGGLES_TOTAL = pc.Counter(
    'frontend_local_model_toggles_total',
    'Local model toggle events by action.',
    ['action']
)


def personality_html(name):
    """Return banner HTML + a <style> tag that sets the accent CSS variable."""
    s = api.get_personality_style(name)
    accent = s["accent"]
    emoji = s["emoji"]
    return (
        f"<style>:root {{ --accent: {accent}; --accent-tint: {accent}18; }}</style>"
        f'<div style="padding:10px 14px; border-radius:8px; font-weight:600;'
        f" background:{accent}15; color:{accent};"
        f' border-left:4px solid {accent}; display:flex; align-items:center;">'
        f'<span style="font-size:1.3em; margin-right:8px;">{emoji}</span>{name}</div>'
    )


def update_profile(personality, session_id):
    """Switch personality: clear chat, update banner and memory display."""
    FRONTEND_PERSONALITY_SWITCHES_TOTAL.labels(personality=personality).inc()
    memory_items = api.get_memory(session_id, personality)
    return [], [], memory_items, None, personality_html(personality)

def _flatten_content(content):
    """Extract plain text from Gradio 6.x message content (list of parts or string)."""
    if isinstance(content, str):
        return content
    return "".join(part["text"] for part in content if isinstance(part, dict) and part.get("type") == "text")


def chat(message, history, personality, max_tokens, temperature, top_p,
         session_id, min_recall_importance, min_save_importance, recent_turns, use_local):
    FRONTEND_CHAT_REQUESTS_TOTAL.inc()
    started = perf_counter()

    api_history = [
        {"role": msg["role"], "content": _flatten_content(msg["content"])}
        for msg in history
    ]

    settings = {
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "top_p": float(top_p),
        "min_recall_importance": int(min_recall_importance),
        "min_save_importance": int(min_save_importance),
        "recent_turns": int(recent_turns),
    }

    try:
        result = api.send_message(message, api_history, personality, settings, session_id, use_local)
    except Exception as e:
        FRONTEND_CHAT_ERRORS_TOTAL.labels(error_type="backend").inc()
        return f"Error: {e}", gr.skip()
    finally:
        FRONTEND_CHAT_DURATION_SECONDS.observe(perf_counter() - started)

    return result["response"], result["memory_items"]

CSS = """
.chat-col { border-top: 3px solid var(--accent, #2563EB); border-radius: 8px; padding-top: 8px; }
.chat-col .bot .message-bubble { border-color: var(--accent, #2563EB) !important; }
.memory-accordion { border-color: var(--accent, #2563EB) !important; }
"""

with gr.Blocks(css=CSS) as demo:
    session_id = gr.State(None)
    demo.load(fn=lambda: str(uuid.uuid4()), outputs=[session_id])

    with gr.Row():
        settings = SettingsSidebar(PERSONALITIES, DEFAULT_PERSONALITY)

        with gr.Column(scale=1, elem_classes=["chat-col"]):
            banner = gr.HTML(value=personality_html(DEFAULT_PERSONALITY))

            memory_display = gr.JSON(value=[], label="Stored memory items", render=False)

            chatbot = gr.ChatInterface(
                chat,
                additional_inputs=[
                    settings["personality_dd"],
                    settings["max_tokens"],
                    settings["temperature"],
                    settings["top_p"],
                    session_id,
                    settings["min_recall_importance"],
                    settings["min_save_importance"],
                    settings["recent_turns"],
                    settings["local_toggle"],
                ],
                additional_outputs=[memory_display],
            )
            with gr.Accordion("Memory", open=True, elem_classes=["memory-accordion"]):
                memory_display.render()

    settings["personality_dd"].change(
        fn=update_profile,
        inputs=[settings["personality_dd"], session_id],
        outputs=[
            chatbot.chatbot,
            chatbot.chatbot_state,
            memory_display,
            chatbot.saved_input,
            banner,
        ],
    )

    settings["local_toggle"].change(
        fn=lambda enabled: FRONTEND_LOCAL_MODEL_TOGGLES_TOTAL.labels(action="on" if enabled else "off").inc(),
        inputs=[settings["local_toggle"]],
    )

if __name__ == "__main__":
    pc.start_http_server(9090)
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", "7860")),
    )
