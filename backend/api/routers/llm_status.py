"""CLAUDE.md §5a: expose the currently-active LLM tier to the frontend for
the "active tier" dashboard indicator."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..run_manager import RunManager
from ..state import get_run_manager

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
def status(run_manager: RunManager = Depends(get_run_manager)) -> dict:
    tier = run_manager.active_llm_tier()
    return {"active_tier": tier, "available": tier is not None}
