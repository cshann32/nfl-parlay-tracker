"""
Application factory — create_app().
Wires together config, extensions, blueprints, and error handlers.
"""
import logging
import os

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

from app.config import get_config
from app.extensions import db, migrate, login_manager, bcrypt, csrf, scheduler, init_redis
from app.logging_config import setup_logging, inject_request_id
from app.exceptions import (
    NFLTrackerException, AuthException, LoginRequiredException,
    RoleRequiredException, ValidationException,
)

load_dotenv()


def create_app(config_class=None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ── Config ────────────────────────────────────────────────────────────────
    cfg = config_class or get_config()
    app.config.from_object(cfg)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["LOG_DIR"], exist_ok=True)

    # ── Enforce SECRET_KEY in production ──────────────────────────────────────
    if not app.debug and app.config.get("SECRET_KEY", "") in ("", "dev-secret-change-me"):
        raise RuntimeError(
            "SECRET_KEY environment variable must be set to a strong random value in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # ── Logging ───────────────────────────────────────────────────────────────
    setup_logging(app)
    inject_request_id(app)

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"
    csrf.init_app(app)
    init_redis(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    _register_blueprints(app)

    # ── Error handlers ────────────────────────────────────────────────────────
    _register_error_handlers(app)

    # ── Security headers ──────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if not app.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # ── Scheduler ─────────────────────────────────────────────────────────────
    _start_scheduler(app)

    # ── Context processors ────────────────────────────────────────────────────
    from app.context_processors import inject_stat_labels
    app.context_processor(inject_stat_labels)

    # ── Shell context ─────────────────────────────────────────────────────────
    @app.shell_context_processor
    def shell_ctx():
        from app import models
        return {"db": db, "models": models}

    logger = logging.getLogger("nfl.app")
    logger.info("NFL Parlay Tracker started", extra={"env": app.config.get("FLASK_ENV")})
    return app


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import dashboard_bp
    from app.blueprints.parlays import parlays_bp
    from app.blueprints.stats import stats_bp
    from app.blueprints.schedules import schedules_bp
    from app.blueprints.uploads import uploads_bp
    from app.blueprints.reports import reports_bp
    from app.blueprints.api import api_bp
    from app.blueprints.admin import admin_bp

    app.register_blueprint(auth_bp,      url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/")
    app.register_blueprint(parlays_bp,   url_prefix="/parlays")
    app.register_blueprint(stats_bp,     url_prefix="/stats")
    app.register_blueprint(schedules_bp, url_prefix="/schedules")
    app.register_blueprint(uploads_bp,   url_prefix="/uploads")
    app.register_blueprint(reports_bp,   url_prefix="/reports")
    app.register_blueprint(api_bp,       url_prefix="/api")
    app.register_blueprint(admin_bp,     url_prefix="/admin")

    # API routes use JSON — exempt from form-based CSRF validation
    csrf.exempt(api_bp)


def _register_error_handlers(app: Flask) -> None:
    logger = logging.getLogger("nfl.app")

    @app.errorhandler(400)
    def bad_request(e):
        logger.warning("400 bad request", extra={"error": str(e)})
        if _wants_json():
            return jsonify(error="Bad Request", message=str(e)), 400
        return render_template("errors/400.html", error=e), 400

    @app.errorhandler(401)
    def unauthorized(e):
        logger.warning("401 unauthorized", extra={"error": str(e)})
        if _wants_json():
            return jsonify(error="Unauthorized", message=str(e)), 401
        return render_template("errors/401.html", error=e), 401

    @app.errorhandler(403)
    def forbidden(e):
        logger.warning("403 forbidden", extra={"error": str(e)})
        if _wants_json():
            return jsonify(error="Forbidden", message=str(e)), 403
        return render_template("errors/403.html", error=e), 403

    @app.errorhandler(404)
    def not_found(e):
        logger.info("404 not found", extra={"error": str(e)})
        if _wants_json():
            return jsonify(error="Not Found", message=str(e)), 404
        return render_template("errors/404.html", error=e), 404

    @app.errorhandler(413)
    def too_large(e):
        logger.warning("413 payload too large")
        if _wants_json():
            return jsonify(error="File Too Large", message="Max upload size is 50 MB"), 413
        return render_template("errors/413.html"), 413

    @app.errorhandler(LoginRequiredException)
    def login_required_handler(e):
        logger.info("Login required", extra=e.detail)
        if _wants_json():
            return jsonify(e.to_dict()), 401
        return render_template("errors/401.html", error=e), 401

    @app.errorhandler(RoleRequiredException)
    def role_required_handler(e):
        logger.warning("Role required", extra=e.detail)
        if _wants_json():
            return jsonify(e.to_dict()), 403
        return render_template("errors/403.html", error=e), 403

    @app.errorhandler(ValidationException)
    def validation_handler(e):
        logger.info("Validation error", extra=e.detail)
        if _wants_json():
            return jsonify(e.to_dict()), 400
        return render_template("errors/400.html", error=e), 400

    @app.errorhandler(NFLTrackerException)
    def nfl_tracker_handler(e):
        logger.error("Application error: %s", e.message, extra=e.detail, exc_info=True)
        if _wants_json():
            return jsonify(e.to_dict()), e.status_code
        return render_template("errors/500.html", error=e), e.status_code

    @app.errorhandler(500)
    def internal_error(e):
        logger.critical("500 internal server error", exc_info=True)
        if _wants_json():
            return jsonify(error="Internal Server Error", message="An unexpected error occurred"), 500
        return render_template("errors/500.html", error=e), 500


def _start_scheduler(app: Flask) -> None:
    if app.config.get("SCHEDULER_ENABLED") and not app.config.get("TESTING"):
        from app.services.sync import run_full_sync
        interval_hours = app.config.get("SYNC_INTERVAL_HOURS", 24)
        scheduler.add_job(
            func=lambda: run_full_sync(app),
            trigger="interval",
            hours=interval_hours,
            id="nfl_full_sync",
            replace_existing=True,
        )
        scheduler.start()
        logging.getLogger("nfl.app").info(
            "Scheduler started", extra={"interval_hours": interval_hours}
        )


def _wants_json() -> bool:
    return request.accept_mimetypes.best == "application/json" or \
           request.path.startswith("/api/")
