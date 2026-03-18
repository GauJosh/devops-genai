from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenerateRequest(BaseModel):
    request_id: Optional[str] = None
    tenant_id: Optional[str] = None
    purpose: Optional[str] = "rag"
    model_hint: Optional[str] = None

    messages: List[ChatMessage]

    temperature: float = 0.2
    max_tokens: int = 800
    timeout_ms: int = 30000

    # room for future: tool calls, response format, etc.
    extra: Dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class GenerateResponse(BaseModel):
    provider: str
    model_used: str
    output_text: str
    usage: Usage
    latency_ms: int