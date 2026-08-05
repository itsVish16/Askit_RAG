"""In-process SQS consumer that runs the worker LangGraph per message."""

import threading
import time

from opik.integrations.langchain import OpikTracer

from app.config import settings
from app.core.logger import get_logger
from app.ingest_worker.flow import worker_agent
from app.queue import sqs
from app.queue import status as job_status

logger = get_logger(__name__)

_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def start_worker_thread() -> None:
    """Spawn the daemon thread that consumes ingest messages."""
    global _stop_event, _thread
    if not settings.INGEST_WORKER_ENABLED:
        logger.info("  [ingest_worker] INGEST_WORKER_ENABLED=false — worker thread NOT started.")
        return
    if not sqs.is_configured():
        logger.warning(
            "  [ingest_worker] SQS_QUEUE_URL not set — worker thread NOT started "
            "(set INGEST_WORKER_ENABLED=true + SQS_QUEUE_URL to enable async ingest)."
        )
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_worker_loop, name="ingest-worker", daemon=True)
    _thread.start()
    logger.info("  [ingest_worker] worker thread started (daemon).")


def stop_worker_thread(timeout: float = 5.0) -> None:
    """Signal the long-poll loop to exit and join with a timeout."""
    global _stop_event, _thread
    if _stop_event is None or _thread is None:
        return
    _stop_event.set()
    _thread.join(timeout=timeout)
    if _thread.is_alive():
        logger.warning("  [ingest_worker] thread did not stop within timeout — it will die with the process.")
    else:
        logger.info("  [ingest_worker] worker thread stopped.")
    _stop_event = None
    _thread = None


def _worker_loop() -> None:
    logger.info("[ingest_worker] polling SQS...")
    while _stop_event is not None and not _stop_event.is_set():
        try:
            msg = sqs.receive_one()
        except Exception as exc:
            logger.error(f"  [ingest_worker] receive error: {exc} — backing off 10s")
            _sleep_interruptible(10)
            continue
        if msg is None:
            continue
        _process_message(msg)
    logger.info("[ingest_worker] stop_event set — exiting loop.")


def _process_message(msg: dict) -> None:
    """Run one job through the worker LangGraph, then handle SQS lifecycle."""
    job_id = msg.get("job_id", "<no-job-id>")
    receipt = msg.get("receipt_handle", "")
    file_path = msg.get("file_path", "")
    user_id = msg.get("user_id", "")
    sha256 = msg.get("sha256", "")
    attempts = max(int(msg.get("attempts", 0)), int(msg.get("receive_count", 0)) - 1)

    logger.info(f"[ingest_worker] picked job {job_id} (attempt {attempts + 1}) user={user_id} file={file_path}")
    job_status.set_state(job_id, "PROCESSING", attempts=attempts + 1)

    try:
        result = worker_agent.invoke(
            {
                "job_id": job_id,
                "file_path": file_path,
                "user_id": user_id,
                "sha256": sha256,
                "attempts": attempts,
                "error_type": None,
                "last_error": None,
            },
            config={"callbacks": [OpikTracer(thread_id=job_id)]},
        )
        final = result.get("final_state", "COMPLETED")
    except Exception as exc:
        # An escape from the graph itself (not a node-set error) is transient —
        # the deterministic point_id makes re-running safe even if a state
        # transition already happened.
        logger.error(f"  [ingest_worker] graph escape for {job_id}: {type(exc).__name__}: {exc}")
        job_status.set_state(job_id, "RETRYING", attempts=attempts + 1, error=str(exc))
        final = "RETRYING"

    if final == "RETRYING":
        logger.info(f"  [ingest_worker] job {job_id} RETRYING — leaving SQS message for visibility-timeout redelivery")
        return

    if receipt:
        try:
            sqs.delete_message(receipt)
        except Exception as exc:
            logger.warning(f"[ingest_worker] WARNING: failed to delete SQS msg for {job_id}: {exc}")
    logger.info(f"[ingest_worker] job {job_id} {final} — SQS message deleted.")


def _sleep_interruptible(seconds: float) -> None:
    """time.sleep that returns early when stop_event is set."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _stop_event is not None and _stop_event.is_set():
            return
        time.sleep(min(0.5, deadline - time.monotonic()))
