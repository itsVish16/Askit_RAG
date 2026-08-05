import logging
import sys
from contextvars import ContextVar

# Context variable to hold the current session ID or request ID
_session_id_ctx: ContextVar[str | None] = ContextVar("session_id", default=None)

def set_session_id(session_id: str) -> None:
    """Set the session ID for the current context."""
    _session_id_ctx.set(session_id)

def get_session_id() -> str | None:
    """Get the current session ID."""
    return _session_id_ctx.get()

class SessionContextFilter(logging.Filter):
    """Filter that injects the session_id from contextvars into the log record."""
    def filter(self, record: logging.LogRecord) -> bool:
        session_id = get_session_id()
        record.session_id = session_id if session_id else "-"
        return True

def setup_logging():
    """Configure the root logger."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return  # already configured

    root_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    
    # Format: [TIME] [LEVEL] [SESSION_ID] [LOGGER] MESSAGE
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(session_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    
    # Attach filter to inject session_id
    filter_ = SessionContextFilter()
    handler.addFilter(filter_)
    
    root_logger.addHandler(handler)

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance configured with the session context filter."""
    setup_logging()
    logger = logging.getLogger(name)
    # Filter must also be added to the logger itself for custom loggers
    # if we want the attributes available before it bubbles to root.
    if not any(isinstance(f, SessionContextFilter) for f in logger.filters):
        logger.addFilter(SessionContextFilter())
    return logger
