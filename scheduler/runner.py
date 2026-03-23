"""
Scheduler — orchestrates all data refresh cycles.
Equivalent to V8.0 Triggers.js with configurable presets.
Uses APScheduler (pip install apscheduler).
"""

from __future__ import annotations
import logging
import time
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import SCHEDULER_CONFIG

logger = logging.getLogger(__name__)


class MLBScheduler:
    """
    Manages all time-based refresh jobs for the MLB system.

    Presets mirror V8.0 Triggers.js:
      - "gameday"       — high frequency (odds 10min, predictions 5min)
      - "active"        — moderate (odds 15min, predictions 5min)
      - "low_activity"  — off-season (odds 2h, predictions 30min)
      - "default"       — standard intervals from settings
    """

    PRESETS = {
        "gameday": {
            "odds_min": 10,
            "injuries_min": 60,
            "weather_min": 120,
            "dk_splits_min": 60,
            "pitchers_min": 30,
            "bullpens_min": 60,
            "live_predictions_min": 5,
        },
        "active": {
            "odds_min": 15,
            "injuries_min": 90,
            "weather_min": 180,
            "dk_splits_min": 90,
            "pitchers_min": 45,
            "bullpens_min": 90,
            "live_predictions_min": 5,
        },
        "low_activity": {
            "odds_min": 120,
            "injuries_min": 240,
            "weather_min": 480,
            "dk_splits_min": 240,
            "pitchers_min": 120,
            "bullpens_min": 240,
            "live_predictions_min": 30,
        },
    }

    def __init__(self, pipeline: "MLBPipeline"):  # type: ignore[name-defined]
        self.pipeline = pipeline
        self._scheduler = BackgroundScheduler()
        self._running = False
        logger.debug("MLBScheduler initialised")

    def start(self, preset: str = "default") -> None:
        intervals = self._resolve_intervals(preset)
        logger.info(
            "Scheduler starting with preset='%s' — intervals: "
            "odds=%dmin  injuries=%dmin  weather=%dmin  "
            "dk_splits=%dmin  pitchers=%dmin  bullpens=%dmin  predictions=%dmin",
            preset,
            intervals["odds_min"],
            intervals["injuries_min"],
            intervals["weather_min"],
            intervals["dk_splits_min"],
            intervals["pitchers_min"],
            intervals["bullpens_min"],
            intervals["live_predictions_min"],
        )
        self._add_jobs(intervals)
        self._scheduler.start()
        self._running = True
        logger.info("Scheduler started with preset='%s'", preset)

    def stop(self) -> None:
        logger.info("Scheduler stopping...")
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Scheduler stopped")

    def run_once(self) -> None:
        """Run a full single refresh cycle immediately (no scheduling)."""
        logger.info("Scheduler.run_once — triggering full refresh now")
        t0 = time.time()
        self.pipeline.run_full_refresh()
        ms = int((time.time() - t0) * 1000)
        logger.info("Scheduler.run_once complete in %.1fs", ms / 1000)

    def _resolve_intervals(self, preset: str) -> dict:
        if preset in self.PRESETS:
            logger.debug("Scheduler: using built-in preset '%s'", preset)
            return self.PRESETS[preset]
        logger.debug("Scheduler: no preset '%s' — using settings.SCHEDULER_CONFIG", preset)
        cfg = SCHEDULER_CONFIG
        return {
            "odds_min": cfg.odds_min,
            "injuries_min": cfg.injuries_min,
            "weather_min": cfg.weather_min,
            "dk_splits_min": cfg.dk_splits_min,
            "pitchers_min": cfg.pitchers_min,
            "bullpens_min": cfg.bullpens_min,
            "live_predictions_min": cfg.live_predictions_min,
        }

    def _add_jobs(self, intervals: dict) -> None:
        sched = self._scheduler
        pipe = self.pipeline

        def _wrap(fn, job_id: str):
            """Wrapper that logs job start/end and duration."""
            def wrapped():
                logger.info("Scheduler job '%s' triggered at %s", job_id, datetime.utcnow().isoformat())
                t0 = time.time()
                try:
                    fn()
                    ms = int((time.time() - t0) * 1000)
                    logger.info("Scheduler job '%s' completed in %dms", job_id, ms)
                except Exception as exc:
                    ms = int((time.time() - t0) * 1000)
                    logger.error(
                        "Scheduler job '%s' FAILED after %dms: %s",
                        job_id, ms, exc, exc_info=True,
                    )
            wrapped.__name__ = job_id
            return wrapped

        sched.add_job(_wrap(pipe.refresh_odds,            "odds"),
                      IntervalTrigger(minutes=intervals["odds_min"]),
                      id="odds",        replace_existing=True)
        sched.add_job(_wrap(pipe.refresh_injuries,        "injuries"),
                      IntervalTrigger(minutes=intervals["injuries_min"]),
                      id="injuries",    replace_existing=True)
        sched.add_job(_wrap(pipe.refresh_weather,         "weather"),
                      IntervalTrigger(minutes=intervals["weather_min"]),
                      id="weather",     replace_existing=True)
        sched.add_job(_wrap(pipe.refresh_dk_splits,       "dk_splits"),
                      IntervalTrigger(minutes=intervals["dk_splits_min"]),
                      id="dk_splits",   replace_existing=True)
        sched.add_job(_wrap(pipe.refresh_pitchers,        "pitchers"),
                      IntervalTrigger(minutes=intervals["pitchers_min"]),
                      id="pitchers",    replace_existing=True)
        sched.add_job(_wrap(pipe.refresh_bullpens,        "bullpens"),
                      IntervalTrigger(minutes=intervals["bullpens_min"]),
                      id="bullpens",    replace_existing=True)
        sched.add_job(_wrap(pipe.update_live_predictions, "predictions"),
                      IntervalTrigger(minutes=intervals["live_predictions_min"]),
                      id="predictions", replace_existing=True)

        logger.debug(
            "Scheduler jobs registered: odds(%dmin) injuries(%dmin) weather(%dmin) "
            "dk_splits(%dmin) pitchers(%dmin) bullpens(%dmin) predictions(%dmin)",
            intervals["odds_min"], intervals["injuries_min"], intervals["weather_min"],
            intervals["dk_splits_min"], intervals["pitchers_min"], intervals["bullpens_min"],
            intervals["live_predictions_min"],
        )
