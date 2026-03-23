from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from web.state import start_scheduler, stop_scheduler, scheduler_status, get_pipeline

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

VALID_PRESETS = {"default", "gameday", "active", "low_activity"}


class SchedulerAction(BaseModel):
    action: str        # "start" | "stop"
    preset: str = "default"


@router.get("")
def get_status():
    return scheduler_status()


@router.post("")
def control_scheduler(req: SchedulerAction):
    if req.action == "start":
        preset = req.preset if req.preset in VALID_PRESETS else "default"
        start_scheduler(preset)
        return {"success": True, "status": scheduler_status()}
    elif req.action == "stop":
        stop_scheduler()
        return {"success": True, "status": scheduler_status()}
    return {"success": False, "detail": "Unknown action"}


@router.post("/run-now")
def run_now():
    """Trigger a manual full refresh immediately."""
    pipe = get_pipeline()
    picks = pipe.run_full_refresh()
    return {"success": True, "picks_found": len(picks)}
