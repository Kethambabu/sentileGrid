from __future__ import annotations

from fastapi import APIRouter

from ...database.audit import verify_chain

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify")
def verify() -> dict:
    result = verify_chain()
    return {"ok": result.ok, "rows_checked": result.rows_checked, "first_broken_id": result.first_broken_id, "reason": result.reason}
