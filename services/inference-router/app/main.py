from fastapi import FastAPI, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from .routes import router

app = FastAPI(title="inference-router", version="0.1.0")
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)