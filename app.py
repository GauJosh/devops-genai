import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

app = FastAPI(title="DevOps GenAI Assistant")

client = OpenAI(api_key=api_key) if api_key else None


class ChatRequest(BaseModel):
    prompt: str


@app.get("/healthz")
def healthz():
    return {"status": "ok", "model": model}


@app.post("/chat")
def chat(req: ChatRequest):
    if not api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set in .env")

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful DevOps assistant."},
                {"role": "user", "content": req.prompt},
            ],
        )
        return {
            "answer": resp.choices[0].message.content,
            "usage": resp.usage.model_dump() if resp.usage else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))