import time
from openai import OpenAI
from ..schemas import GenerateRequest, GenerateResponse, Usage
from ..config import OPENAI_API_KEY, OPENAI_MODEL_DEFAULT


class OpenAIAdapter:
    provider = "openai"

    def __init__(self):
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=OPENAI_API_KEY)

    def _estimate_cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = {
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        }
        p = pricing.get(model)
        if not p:
            return 0.0
        return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]

    def generate(self, req: GenerateRequest) -> GenerateResponse:
        model = req.model_hint or OPENAI_MODEL_DEFAULT
        t0 = time.time()

        messages = [{"role": m.role, "content": m.content} for m in req.messages]

        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            timeout=req.timeout_ms / 1000.0,
        )

        latency_ms = int((time.time() - t0) * 1000)
        text = resp.choices[0].message.content or ""

        usage = resp.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        cost = self._estimate_cost_usd(model, input_tokens, output_tokens)

        return GenerateResponse(
            provider=self.provider,
            model_used=model,
            output_text=text,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            ),
            latency_ms=latency_ms,
        )