from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter
from utils.logger import FeedHealthMonitor, ScheduleLogger

router = APIRouter(prefix="/api/health", tags=["health"])

_feed_monitor = FeedHealthMonitor()
_schedule_logger = ScheduleLogger()


@router.get("")
def get_health():
    return {
        "feeds": _feed_monitor.get_all(),
        "schedule_log": _schedule_logger.get_recent(limit=20),
        "checked_at": datetime.utcnow().isoformat(),
    }
