import datetime
import logging
from typing import Dict, Optional, Any
# Ensure imports use the correct relative path if run as part of a package
# If running scripts directly, ensure PYTHONPATH is set or use absolute imports if needed.
from .state import LogEntry, LogLevel, TranslationState

# --- Logging Utility ---
def log_to_state(state: TranslationState, message: str, level: LogLevel = "INFO", node: Optional[str] = None):
    """Appends a structured log entry to the graph state."""
    if not isinstance(state, dict): state = {} # Ensure state is a dict
    if "logs" not in state or not isinstance(state["logs"], list):
        state["logs"] = []
    entry = LogEntry(
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        level=level,
        message=message,
        node=node or state.get("current_step") # Use current step if node not provided
    )
    state["logs"].append(entry)
    # Optionally print logs to console as well during development
    # print(f"LOG: [{entry['timestamp']}] [{entry['level']}] [{entry.get('node','N/A')}] {entry['message']}") # Disabled duplicate console log
    # Also log to the file logger
    logger = logging.getLogger("turjuman")
    log_msg = f"[{entry['level']}] [{entry.get('node','N/A')}] {entry['message']}"
    if level == "DEBUG":
        logger.debug(log_msg)
    elif level == "INFO":
        logger.info(log_msg)
    elif level == "WARNING":
        logger.warning(log_msg)
    elif level == "ERROR":
        logger.error(log_msg)
    elif level == "CRITICAL":
        logger.critical(log_msg)
    else:
        logger.info(log_msg)
    

# --- Progress Utility ---
def update_progress(state: TranslationState, step: str, percent: Optional[float] = None):
    """Updates the current step and progress percentage in the state."""
    if not isinstance(state, dict): state = {} # Ensure state is a dict
    state["current_step"] = step
    if percent is not None:
        state["progress_percent"] = max(0.0, min(100.0, percent))
    # Log the progress update
    progress_str = f" ({state.get('progress_percent', 0.0):.1f}%)" if state.get('progress_percent') is not None else ""
    log_to_state(state, f"Entering step: {step}{progress_str}", "DEBUG", node=step)


# --- Token Counting Utility ---


