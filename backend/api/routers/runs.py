from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from ..run_manager import RunManager
from ..schemas import StartRunRequest, StartRunResponse
from ..state import get_run_manager

router = APIRouter(prefix="/runs", tags=["runs"])

WS_POLL_SECONDS = 0.5


@router.post("", response_model=StartRunResponse)
def start_run(request: StartRunRequest, run_manager: RunManager = Depends(get_run_manager)) -> StartRunResponse:
    try:
        run_id = run_manager.start_run(
            request.scenario_name, duration_hours=request.duration_hours,
            tick_seconds=request.tick_seconds, assessment_interval_records=request.assessment_interval_records,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StartRunResponse(run_id=run_id)


@router.get("/{run_id}")
def get_run(run_id: str, run_manager: RunManager = Depends(get_run_manager)) -> dict:
    state = run_manager.get_run(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    return state.snapshot()


@router.get("/{run_id}/assessments")
def get_assessments(run_id: str, run_manager: RunManager = Depends(get_run_manager)) -> list[dict]:
    state = run_manager.get_run(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    with state.lock:
        return list(state.assessments)


@router.get("/{run_id}/readings")
def get_readings(run_id: str, run_manager: RunManager = Depends(get_run_manager)) -> list[dict]:
    state = run_manager.get_run(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    with state.lock:
        return list(state.record_history)


@router.websocket("/ws/{run_id}")
async def run_updates(websocket: WebSocket, run_id: str, run_manager: RunManager = Depends(get_run_manager)) -> None:
    await websocket.accept()
    last_revealed = -1
    last_assessment_count = -1
    try:
        while True:
            state = run_manager.get_run(run_id)
            if state is None:
                await websocket.send_json({"type": "error", "message": f"No run with id {run_id}"})
                break

            snapshot = state.snapshot()
            if snapshot["revealed_count"] != last_revealed or snapshot["assessment_count"] != last_assessment_count:
                await websocket.send_json({"type": "update", **snapshot})
                last_revealed = snapshot["revealed_count"]
                last_assessment_count = snapshot["assessment_count"]

            if snapshot["status"] in ("completed", "error"):
                break
            await asyncio.sleep(WS_POLL_SECONDS)
    except WebSocketDisconnect:
        pass
