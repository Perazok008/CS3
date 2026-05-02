import json
from pathlib import Path

MEMORY_FILE = Path(__file__).parent / "memory.json"

def _load() -> dict:
    if MEMORY_FILE.exists():
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {}

def _save(store: dict):
    with open(MEMORY_FILE, "w") as f:
        json.dump(store, f, indent=2)

def get_personality_memory(user_id: str, personality: str) -> list[dict]:
    return list(_load().get(user_id, {}).get(personality.lower(), []))

def save_personality_memory(user_id: str, personality: str, items: list[dict]):
    store = _load()
    store.setdefault(user_id, {})[personality.lower()] = items
    _save(store)

def delete_personality_memory(user_id: str, personality: str):
    store = _load()
    if user_id in store and personality.lower() in store[user_id]:
        del store[user_id][personality.lower()]
        _save(store)