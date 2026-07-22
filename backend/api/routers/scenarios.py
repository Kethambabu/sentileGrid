from fastapi import APIRouter

from ..run_manager import list_scenarios

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("")
def get_scenarios() -> list[dict]:
    return [
        {"name": s.name, "description": s.description.strip(), "duration_hours": s.duration_hours}
        for s in list_scenarios()
    ]
