from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, settings
from .ops import AuditLog, RateLimiter

log = logging.getLogger("fedsight")
WEB = ROOT / "web"


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=settings.max_question_chars)
    sources: list[str] | None = Field(default=None, description="Any of gao, fema, cdc. Omit for all.")


def build_state(app: FastAPI, agent=None, limiter=None):
    """Loads the index, database and Claude client. Tests pass their own agent."""
    if agent is None:
        import anthropic

        from .agent import Agent
        from .search import load_index
        from .tables import ReadOnlyDB

        agent = Agent(anthropic.Anthropic(max_retries=2, timeout=60), load_index(), ReadOnlyDB())
    app.state.agent = agent
    app.state.limiter = limiter or RateLimiter(settings.rate_limit_per_hour, settings.daily_question_cap)
    app.state.audit = AuditLog(Path(os.getenv("FEDSIGHT_AUDIT_FILE")) if os.getenv("FEDSIGHT_AUDIT_FILE") else None)


def create_app(agent=None, limiter=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        build_state(app, agent, limiter)
        yield

    app = FastAPI(title="FedSight API", version="1.0",
                  description="Cited answers over GAO reports, FEMA guidance and CDC data.", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        a = app.state.agent
        return {"status": "ok", "chunks": len(a.index.chunks), "tables": list(a.db.loaded), "model": a.model}

    @app.get("/api/sources")
    def sources():
        docs_file = settings.data_dir / "corpus" / "documents.jsonl"
        docs = [json.loads(line) for line in docs_file.read_text().splitlines()] if docs_file.exists() else []
        return {"documents": docs, "tables": app.state.agent.db.loaded}

    @app.get("/api/evals")
    def evals():
        f = ROOT / "evals" / "results" / "latest.json"
        if not f.exists():
            raise HTTPException(404, "No eval run yet")
        data = json.loads(f.read_text())
        data.pop("rows", None)
        return data

    @app.post("/api/ask")
    def ask(body: AskRequest, request: Request):
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
        client_id = app.state.audit.hash_client(ip)
        limited = app.state.limiter.check(client_id)
        if limited:
            return JSONResponse({"error": limited}, status_code=429)
        bad = [s for s in (body.sources or []) if s not in settings.sources]
        if bad:
            raise HTTPException(422, f"Unknown source(s): {bad}")
        try:
            result = app.state.agent.ask(body.question, body.sources)
        except Exception as e:
            log.exception("ask failed")
            app.state.audit.write({"event": "error", "client": client_id, "error": type(e).__name__})
            return JSONResponse({"error": "Something went wrong answering that. Please try again."}, status_code=502)
        app.state.audit.write({
            "event": "ask", "request_id": result.request_id, "client": client_id,
            "question": result.question, "sources_filter": body.sources,
            "tools": [{"tool": s.tool, "input": s.input, "ok": s.ok} for s in result.steps],
            "cited": [s["source"] for s in result.sources if s.get("cited_as")],
            "guardrails": result.guardrails, "usage": result.usage,
        })
        return result.as_dict()

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()
