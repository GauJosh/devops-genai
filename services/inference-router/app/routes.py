from fastapi import APIRouter, HTTPException
from .schemas import GenerateRequest, GenerateResponse
from .adapters.openai_adapter import OpenAIAdapter

router = APIRouter()

_openai = OpenAIAdapter()

@router.post("/v1/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    # v1: only openai provider; routing logic will grow later
    try:
        return _openai.generate(req)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Inference failed: {e}")