"""FastAPI app (CLAUDE.md §3/§5: FastAPI, not Flask/Django). The frontend
talks to this and only this — never directly to backend/database or
backend/orchestrator.

Run: uvicorn backend.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import approvals, audit, llm_status, runs, scenarios

app = FastAPI(title="SentinelGrid API", version="0.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(scenarios.router)
app.include_router(runs.router)
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(llm_status.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
