import requests
import time
from ..schemas import GenerateRequest, GenerateResponse, Usage
from ..config import OLLAMA_BASE_URL, OLLAMA_DEFAULT_MODEL


class OllamaAdapter:
    provider = "ollama"

    def generate(self, req: GenerateRequest) -> GenerateResponse:
        model = req.model_hint or OLLAMA_DEFAULT_MODEL
        t0 = time.time()

        # Flatten chat messages into a single prompt for Ollama generate API
        prompt_parts = []
        for msg in req.messages:
            prompt_parts.append(f"{msg.role.upper()}:\n{msg.content}")
        prompt = "\n\n".join(prompt_parts)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": req.temperature,
            },
        }

        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=req.timeout_ms / 1000.0,
        )
        resp.raise_for_status()
        data = resp.json()

        latency_ms = int((time.time() - t0) * 1000)

        output_text = data.get("response", "")

        # Ollama may return eval_count / prompt_eval_count
        input_tokens = int(data.get("prompt_eval_count", 0) or 0)
        output_tokens = int(data.get("eval_count", 0) or 0)

        # Local model cost = 0 for this lab
        cost_usd = 0.0

        return GenerateResponse(
            provider=self.provider,
            model_used=model,
            output_text=output_text,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            ),
            latency_ms=latency_ms,
        )