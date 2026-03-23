"""
MLB Betting System — Entry Point

Usage:
    python main.py                     # Run once and exit
    python main.py --schedule          # Run with scheduler (continuous)
    python main.py --schedule gameday  # GameDay preset (high frequency)
    python main.py --log-bet <game_id> # Log a bet from the latest predictions
"""

from __future__ import annotations
import argparse
import signal
import sys
import time

from utils.logger import configure_logging
from pipeline import MLBPipeline
from scheduler.runner import MLBScheduler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MLB Betting Prediction System")
    parser.add_argument("--schedule", nargs="?", const="default", metavar="PRESET",
                        help="Run with scheduler. Preset: default, gameday, active, low_activity")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging level")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    pipeline = MLBPipeline()

    if args.schedule:
        # Continuous mode with scheduler
        scheduler = MLBScheduler(pipeline)

        def shutdown(sig, frame):
            print("\nShutting down scheduler...")
            scheduler.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        # Run an immediate refresh first
        pipeline.run_full_refresh()

        # Then start scheduler
        scheduler.start(preset=args.schedule)
        print(f"Scheduler running (preset='{args.schedule}'). Press Ctrl+C to stop.")
        while True:
            time.sleep(60)
    else:
        # Single run
        predictions = pipeline.run_full_refresh()
        if not predictions:
            print("No qualified picks found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
