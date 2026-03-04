"""
Structured JSON logging configuration.
Sets up rotating file handlers + console handler for every module.
A request_id UUID is injected into every log record during a request.
"""
import logging
import logging.handlers
import os
import uuid
from pythonjsonlogger import jsonlogger
from flask import Flask, g, request, has_request_context


class RequestIdFilter(logging.Filter):
    """Injects request_id and request_path into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if has_request_context():
            record.request_id = getattr(g, "request_id", "no-request")
            record.path = request.path
            record.method = request.method
        else:
            record.request_id = "cli"
            record.path = "-"
            record.method = "-"
        return True


def _make_handler(log_path: str, level: int) -> logging.handlers.RotatingFileHandler:
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(request_id)s %(method)s %(path)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    return handler


def _make_console_handler(level: int) -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setLevel(level)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    return handler


def setup_logging(app: Flask) -> None:
    """Attach structured logging to the Flask app and all module loggers."""
    log_dir = app.config.get("LOG_DIR", "/app/logs")
    os.makedirs(log_dir, exist_ok=True)

    level_name = app.config.get("LOG_LEVEL", "DEBUG")
    level = getattr(logging, level_name.upper(), logging.DEBUG)

    # ── File handlers per concern ──────────────────────────────────────────────
    handlers: dict[str, logging.Handler] = {
        "app":     _make_handler(os.path.join(log_dir, "app.log"), level),
        "sync":    _make_handler(os.path.join(log_dir, "sync.log"), level),
        "uploads": _make_handler(os.path.join(log_dir, "uploads.log"), level),
        "db":      _make_handler(os.path.join(log_dir, "db.log"), level),
        "errors":  _make_handler(os.path.join(log_dir, "errors.log"), logging.ERROR),
    }
    console = _make_console_handler(level)

    # ── Root logger ───────────────────────────────────────────────────────────
    root = logging.getLogger("nfl")
    root.setLevel(level)
    root.addHandler(handlers["app"])
    root.addHandler(handlers["errors"])
    root.addHandler(console)
    root.propagate = False

    # ── Module-specific loggers ───────────────────────────────────────────────
    for name, handler in [("nfl.sync", handlers["sync"]),
                          ("nfl.uploads", handlers["uploads"]),
                          ("nfl.db", handlers["db"])]:
        logger = logging.getLogger(name)
        logger.addHandler(handler)

    app.logger.handlers = root.handlers
    app.logger.setLevel(level)


def inject_request_id(app: Flask) -> None:
    """Register before/after request hooks to attach a UUID request_id."""

    @app.before_request
    def _set_request_id():
        g.request_id = str(uuid.uuid4())

    @app.after_request
    def _log_request(response):
        logger = logging.getLogger("nfl.app")
        logger.info(
            "request completed",
            extra={
                "status_code": response.status_code,
                "content_length": response.content_length,
            },
        )
        return response
