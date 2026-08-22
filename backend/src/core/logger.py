import logging
import sys
from pathlib import Path
from typing import Optional

from .config import settings

# Custom TRACE level, finer-grained than DEBUG. Use for very high-volume
# per-step / per-element diagnostic output (e.g. per-firing simulator events,
# per-place dumps). DEBUG should stay reserved for one-line-per-operation
# summaries that are still readable in normal-sized log files.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]


def setup_logger(
    name: str = "app",
    level: Optional[str] = None,
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """
    Create and configure logger with specified parameters.

    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # If logger is already configured, return it
    if logger.handlers:
        return logger

    # Disable propagation to avoid duplicate logs from parent loggers
    logger.propagate = False

    # Set logging level
    log_level = level or settings.LOG_LEVEL
    level_value = TRACE if log_level.upper() == "TRACE" else getattr(logging, log_level.upper())
    logger.setLevel(level_value)

    # Log format
    formatter = logging.Formatter(
        fmt=settings.LOGGING_FORMAT,
        datefmt=settings.LOGGING_DATE_FORMAT,
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level_value)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if path is specified)
    if log_file or settings.LOG_FILE:
        file_path = log_file or settings.LOG_FILE
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(level_value)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Global application logger instance
_app_logger: Optional[logging.Logger] = None


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get logger for use in application.

    Args:
        name: Optional logger name. If not specified, returns main application logger.

    Returns:
        Logger instance

    Examples:
        >>> logger = get_logger()
        >>> logger.info("Application started")

        >>> api_logger = get_logger("api")
        >>> api_logger.debug("Processing request")
    """
    global _app_logger

    if name:
        # Create child logger with specified name
        return setup_logger(f"app.{name}")

    # Return main application logger
    if _app_logger is None:
        _app_logger = setup_logger("app")

    return _app_logger


def reset_logger() -> None:
    """
    Reset logger settings (useful for tests).
    """
    global _app_logger

    if _app_logger:
        handlers = _app_logger.handlers[:]
        for handler in handlers:
            handler.close()
            _app_logger.removeHandler(handler)
        _app_logger = None


# Export main functions
__all__ = ["get_logger", "setup_logger", "reset_logger", "TRACE"]
