import time

from backend.logging_setup import configure_logging
from backend.settings import get_settings
from backend.workers.tracker_intake import TrackerIntakeWorker, build_tracker_intake_worker


def run(
    *,
    once: bool = False,
    max_iterations: int | None = None,
) -> TrackerIntakeWorker:
    settings = get_settings()
    logger = configure_logging(app_name=settings.app_name, component="worker1")
    logger.info("Starting fetch worker once=%s max_iterations=%s", once, max_iterations)
    worker = build_tracker_intake_worker()
    if once:
        worker.poll_once()
    else:
        worker.run_forever(max_iterations=max_iterations, sleep_fn=time.sleep)
    return worker
