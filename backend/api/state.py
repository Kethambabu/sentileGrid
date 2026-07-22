"""Process-wide RunManager access, via FastAPI dependency injection rather
than a bare module-level singleton — this lets tests override with a
RunManager built from fake LLM providers (see run_manager.py's
constructor), instead of every API test hitting live Hugging Face/Groq
calls just to exercise routing/validation logic.

get_approval_service depends on get_run_manager via FastAPI's own Depends()
chain, not a plain nested function call — that distinction matters:
app.dependency_overrides only rewrites edges FastAPI itself resolves, so a
plain `get_run_manager()` call inside get_approval_service would bypass any
override on get_run_manager and silently fall back to the real cached
singleton.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from .run_manager import RunManager


@lru_cache
def get_run_manager() -> RunManager:
    return RunManager()


def get_approval_service(run_manager: RunManager = Depends(get_run_manager)):
    return run_manager.approval_service
