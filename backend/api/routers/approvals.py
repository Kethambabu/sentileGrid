from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...database.approvals import ApprovalNotFoundError, ApprovalService, ApprovalStatus
from ..schemas import ApprovalDecisionRequest
from ..state import get_approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/{approval_id}")
def get_approval(approval_id: str, approval_service: ApprovalService = Depends(get_approval_service)) -> dict:
    try:
        return approval_service.get(approval_id).model_dump()
    except ApprovalNotFoundError:
        raise HTTPException(status_code=404, detail=f"No approval with id {approval_id}")


@router.post("/{approval_id}/view")
def mark_viewed(approval_id: str, approval_service: ApprovalService = Depends(get_approval_service)) -> dict:
    try:
        return approval_service.mark_evidence_viewed(approval_id).model_dump()
    except ApprovalNotFoundError:
        raise HTTPException(status_code=404, detail=f"No approval with id {approval_id}")


@router.post("/{approval_id}/decide")
def decide(approval_id: str, request: ApprovalDecisionRequest, approval_service: ApprovalService = Depends(get_approval_service)) -> dict:
    try:
        status = ApprovalStatus(request.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"status must be 'approved' or 'rejected', got {request.status!r}")

    try:
        record = approval_service.decide(approval_id, status, operator_id=request.operator_id)
    except ApprovalNotFoundError:
        raise HTTPException(status_code=404, detail=f"No approval with id {approval_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return record.model_dump()
