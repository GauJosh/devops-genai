"""
Inference Router Schemas Module

Pydantic models for request/response validation and serialization for the inference router API.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Literal, Optional, Dict, Any


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenerateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: Optional[str] = None
    tenant_id: Optional[str] = None
    purpose: Optional[str] = "rag"
    model_hint: Optional[str] = None

    messages: List[ChatMessage]

    temperature: float = 0.2
    max_tokens: int = 800
    timeout_ms: int = 30000

    extra: Dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class GenerateResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: str
    model_used: str
    output_text: str
    usage: Usage
    latency_ms: int


class ErrorResponse(BaseModel):
    request_id: Optional[str] = None
    error: str
    provider_attempted: Optional[str] = None
    fallback_attempted: bool = False
    fallback_provider: Optional[str] = None
    failure_stage: str
    detail: str