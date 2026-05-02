from fastapi import FastAPI, HTTPException, status, Response
import prometheus_client as pc
from time import perf_counter

from config import PERSONALITY_CHOICES, PERSONALITIES
from schemas import HealthResponse, PersonalityStyle, ChatRequest, MemoryItem, ChatResponse
from response_manager import respond
from memory_manager import get_personality_memory, delete_personality_memory

BACKEND_REQUESTS_TOTAL = pc.Counter(
    'backend_requests_total',
    'Total requests by endpoint.',
    ['endpoint']
)

BACKEND_REQUESTS_ERRORS_TOTAL = pc.Counter(
    'backend_requests_errors_total',
    'Total requests errors by endpoint.',
    ['endpoint']
)

BACKEND_REQUESTS_DURATION_SECONDS = pc.Histogram(
    'backend_requests_duration_seconds',
    'Duration of requests by model type.',
    ['model_type']
)

BACKEND_ACTIVE_REQUESTS = pc.Gauge(
    'backend_active_requests',
    'Number of in-flight /respond calls.',
)

_SETTING_RANGES = {
    "max_tokens":            (1,   2048),
    "temperature":           (0.1, 4.0),
    "top_p":                 (0.1, 1.0),
    "min_recall_importance": (1,   5),
    "min_save_importance":   (1,   5),
    "recent_turns":          (1,   20),
}

BACKEND_REQUEST_SETTINGS_SELECTED = pc.Histogram(
    'backend_request_settings_selected',
    'Distribution of request settings, normalized to [0, 1] per setting range.',
    ['setting'],
    buckets=[0.2, 0.4, 0.6, 0.8, 1.0],
)

app = FastAPI(
    title="Case Study 2 - Group 6 Backend",
    description="Chatbot API with personality switching and persistent memory.",
    version="1.0.0",
)

@app.get('/metrics')
def metrics():
    return Response(
        pc.generate_latest(),
        media_type=pc.CONTENT_TYPE_LATEST
    )

@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    BACKEND_REQUESTS_TOTAL.labels(endpoint='/health').inc()
    return HealthResponse(status="ok")


@app.get("/personalities", response_model=list[str])
def get_personality_choices() -> list[str]:
    BACKEND_REQUESTS_TOTAL.labels(endpoint='/personalities').inc()
    return PERSONALITY_CHOICES


@app.get(
    "/personalities/style/{personality}",
    response_model=PersonalityStyle,
    responses={404: {"description": "Personality not found"}},
)
def get_personality_style(personality: str) -> PersonalityStyle:
    BACKEND_REQUESTS_TOTAL.labels(endpoint='/personalities/style/personality').inc()
    if personality not in PERSONALITIES:
        BACKEND_REQUESTS_ERRORS_TOTAL.labels(endpoint='/personalities/style/personality').inc()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Personality '{personality}' not found",
        )
    return PersonalityStyle(**PERSONALITIES[personality]["style"])


@app.post(
    "/respond",
    response_model=ChatResponse,
    responses={
        404: {"description": "Personality not found"},
        500: {"description": "Model inference failed"},
    },
)
def respond_to_message(request: ChatRequest) -> ChatResponse:
    BACKEND_REQUESTS_TOTAL.labels(endpoint='/respond').inc()
    model_type = "local" if request.use_local else "api"
    started = perf_counter()
    BACKEND_ACTIVE_REQUESTS.inc()
    try:
        if request.personality not in PERSONALITIES:
            BACKEND_REQUESTS_ERRORS_TOTAL.labels(endpoint='/respond').inc()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Personality '{request.personality}' not found",
            )
        for setting, (lo, hi) in _SETTING_RANGES.items():
            val = getattr(request.settings, setting)
            normalized = (val - lo) / (hi - lo) if hi > lo else 0.5
            BACKEND_REQUEST_SETTINGS_SELECTED.labels(setting=setting).observe(
                min(max(normalized, 0.0), 1.0)
            )
        return respond(request)
    except HTTPException:
        raise
    except Exception as e:
        BACKEND_REQUESTS_ERRORS_TOTAL.labels(endpoint='/respond').inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    finally:
        BACKEND_ACTIVE_REQUESTS.dec()
        BACKEND_REQUESTS_DURATION_SECONDS.labels(model_type=model_type).observe(perf_counter() - started)


@app.get(
    "/memory/{session_id}/{personality}",
    response_model=list[MemoryItem],
    responses={404: {"description": "Personality not found"}},
)
def get_memory(session_id: str, personality: str) -> list[MemoryItem]:
    BACKEND_REQUESTS_TOTAL.labels(endpoint='/memory/session_id/personality').inc()
    if personality not in PERSONALITIES:
        BACKEND_REQUESTS_ERRORS_TOTAL.labels(endpoint='/memory/session_id/personality').inc()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Personality '{personality}' not found",
        )
    return get_personality_memory(session_id, personality)

@app.delete(
    "/memory/{session_id}/{personality}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Personality not found"}},
)
def clear_memory(session_id: str, personality: str):
    BACKEND_REQUESTS_TOTAL.labels(endpoint='/memory/session_id/personality').inc()
    if personality not in PERSONALITIES:
        BACKEND_REQUESTS_ERRORS_TOTAL.labels(endpoint='/memory/session_id/personality').inc()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Personality '{personality}' not found",
        )
    delete_personality_memory(session_id, personality)
