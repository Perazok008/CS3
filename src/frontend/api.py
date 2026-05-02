import os
import requests as rq

DEFAULT_BACKEND_URL = "http://backend:8000"

BACKEND_URL = os.environ.get("BACKEND_URL", DEFAULT_BACKEND_URL)


def get_personalities() -> list[str]:
    response = rq.get(f"{BACKEND_URL}/personalities")
    if response.status_code != 200:
        raise Exception(f"Failed to get personalities: {response.status_code} {response.text}")
    return response.json()

def get_personality_style(personality: str) -> dict:
    response = rq.get(f"{BACKEND_URL}/personalities/style/{personality}")
    if response.status_code != 200:
        raise Exception(f"Failed to get personality style: {response.status_code} {response.text}")
    return response.json()

def send_message(message: str, history: list[dict], personality: str, settings: dict, session_id: str, use_local: bool = False) -> dict:
    response = rq.post(f"{BACKEND_URL}/respond", json={
        "message": message,
        "history": history,
        "personality": personality,
        "settings": settings,
        "session_id": session_id,
        "use_local": use_local,
    }, timeout=120)
    if response.status_code != 200:
        raise Exception(f"Failed to send message: {response.status_code} {response.text}")
    return response.json()

def get_memory(session_id: str, personality: str) -> list[dict]:
    response = rq.get(f"{BACKEND_URL}/memory/{session_id}/{personality}")
    if response.status_code != 200:
        raise Exception(f"Failed to get memory: {response.status_code} {response.text}")
    return response.json()