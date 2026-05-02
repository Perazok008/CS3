from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str

class PersonalityStyle(BaseModel):
    emoji: str
    accent: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatSettings(BaseModel):
    max_tokens: int
    temperature: float
    top_p: float
    min_recall_importance: int
    min_save_importance: int
    recent_turns: int

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage]
    personality: str
    settings: ChatSettings
    session_id: str
    use_local: bool = False

class MemoryItem(BaseModel):
    label: str
    note: str
    importance: int

class ChatResponse(BaseModel):
    response: str
    memory_items: list[MemoryItem]