import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output (prod) or console (dev via LOG_LEVEL=DEBUG).

    PII scrubbing: add custom processors here when logging anything user-provided.
    For now we rely on not logging PHI-adjacent fields anywhere (enforced by
    code review + the forbidden-name list in CLAUDE.md).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
