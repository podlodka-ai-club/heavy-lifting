import time

from backend.workers.tracker_intake import TrackerIntakeWorker, build_tracker_intake_worker


def run(
    *,
    once: bool = False,
    max_iterations: int | None = None,
) -> TrackerIntakeWorker:
    worker = build_tracker_intake_worker()
    if once:
        worker.poll_once()
    else:
        worker.run_forever(max_iterations=max_iterations, sleep_fn=time.sleep)
    return worker
