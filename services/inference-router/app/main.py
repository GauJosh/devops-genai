from fastapi import FastAPI
from .routes import router

app = FastAPI(title="inference-router", version="0.1.0")
app.include_router(router)

@app.get("/healthz")
def healthz():
    return {"ok": True}