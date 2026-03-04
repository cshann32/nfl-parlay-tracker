"""Admin blueprint — user management, sync, scheduler, DB health, log viewer."""
import logging
import os
from datetime import datetime, timezone
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.blueprints.admin import admin_bp
from app.utils.decorators import admin_required
from apscheduler.jobstores.base import JobLookupError as APJobLookupError
from app.extensions import db, scheduler
from app.models.user import User, UserRole
from app.models.sync_log import SyncLog, SyncStatus
from app.models.app_setting import AppSetting
from app.services import db_manager

logger = logging.getLogger("nfl.admin")

VALID_SYNC_CATEGORIES = [
    "all",
    # ── Paid RapidAPI syncs ──────────────────────────
    "seasons", "teams", "coaches", "players", "games",
    "scoreboard", "boxscores", "plays", "stats",
    "odds", "draft", "news",
    # ── ESPN free API syncs (no API key required) ────
    "espn_teams", "espn_roster", "espn_schedule",
    "game_stats", "espn_odds", "espn_news",
]


@admin_bp.route("/")
@login_required
@admin_required
def index():
    db_stats = db_manager.get_db_stats()
    recent_syncs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(10).all()
    user_count = User.query.count()
    scheduler_enabled = AppSetting.get("scheduler_enabled", "false") == "true"
    return render_template("admin/index.html", db_stats=db_stats, recent_syncs=recent_syncs,
                           user_count=user_count, scheduler_enabled=scheduler_enabled)


# ── User Management ───────────────────────────────────────────────────────────

@admin_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/create", methods=["POST"])
@login_required
@admin_required
def create_user():
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "user")

    if not username or not email or not password:
        flash("Username, email, and password are all required.", "danger")
        return redirect(url_for("admin.users"))
    if role not in [r.value for r in UserRole]:
        flash("Invalid role.", "danger")
        return redirect(url_for("admin.users"))
    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' is already taken.", "danger")
        return redirect(url_for("admin.users"))
    if User.query.filter_by(email=email).first():
        flash(f"Email '{email}' is already registered.", "danger")
        return redirect(url_for("admin.users"))

    user = User(username=username, email=email, role=UserRole(role), is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    logger.info("Admin created user", extra={"admin_id": current_user.id, "new_user": username})
    flash(f"User '{username}' created successfully.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower()

    if not username or not email:
        flash("Username and email are required.", "danger")
        return redirect(url_for("admin.users"))
    if User.query.filter(User.username == username, User.id != user_id).first():
        flash(f"Username '{username}' is already taken.", "danger")
        return redirect(url_for("admin.users"))
    if User.query.filter(User.email == email, User.id != user_id).first():
        flash(f"Email '{email}' is already registered.", "danger")
        return redirect(url_for("admin.users"))

    user.username = username
    user.email = email
    db.session.commit()
    logger.info("Admin edited user", extra={"admin_id": current_user.id, "target_user": username})
    flash(f"User '{username}' updated successfully.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@admin_required
def reset_user_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("password", "")
    if len(new_password) < 8:
        flash("Password must be at least 8 characters.", "danger")
        return redirect(url_for("admin.users"))
    user.set_password(new_password)
    db.session.commit()
    logger.info("Admin reset password", extra={"admin_id": current_user.id, "target_user": user.username})
    flash(f"Password for '{user.username}' has been reset.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Cannot delete your own account.", "danger")
        return redirect(url_for("admin.users"))
    username = user.username
    db.session.delete(user)
    db.session.commit()
    logger.info("Admin deleted user", extra={"admin_id": current_user.id, "deleted_user": username})
    flash(f"User '{username}' has been deleted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@login_required
@admin_required
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Cannot deactivate your own account.", "danger")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"User {user.username} {'activated' if user.is_active else 'deactivated'}.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/set-role", methods=["POST"])
@login_required
@admin_required
def set_user_role(user_id):
    user = User.query.get_or_404(user_id)
    role = request.form.get("role")
    if role not in [r.value for r in UserRole]:
        flash("Invalid role.", "danger")
        return redirect(url_for("admin.users"))
    user.role = UserRole(role)
    db.session.commit()
    flash(f"User {user.username} role set to {role}.", "success")
    return redirect(url_for("admin.users"))


# ── Sync Controls ─────────────────────────────────────────────────────────────

@admin_bp.route("/sync", methods=["GET", "POST"])
@login_required
@admin_required
def sync():
    recent = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(30).all()
    return render_template("admin/sync.html", recent=recent, categories=VALID_SYNC_CATEGORIES)


@admin_bp.route("/sync/run", methods=["POST"])
@login_required
@admin_required
def run_sync():
    category = request.form.get("category", "all")
    if category not in VALID_SYNC_CATEGORIES:
        flash(f"Invalid category: {category}", "danger")
        return redirect(url_for("admin.sync"))

    # ESPN-based syncs use the free public API — no key required
    ESPN_FREE = {"game_stats", "espn_odds", "espn_teams", "espn_roster", "espn_schedule", "espn_news"}
    if not current_app.config.get("NFL_API_KEY") and category not in ESPN_FREE and category != "all":
        flash("NFL_API_KEY is not configured — only ESPN free syncs are available.", "warning")
        return redirect(url_for("admin.sync"))

    from app.services.sync import run_sync, run_full_sync
    logger.info("Admin triggered sync", extra={
        "category": category, "admin_id": current_user.id
    })
    if category == "all":
        logs = run_full_sync(current_app._get_current_object(), triggered_by="admin_panel")
        failed = [l for l in logs if l.status == SyncStatus.FAILED]
        flash(f"Full sync complete. {len(logs)} categories run, {len(failed)} failed.", "success")
    else:
        log = run_sync(category, current_app._get_current_object(), triggered_by="admin_panel")
        if log.status == SyncStatus.SUCCESS:
            flash(f"Synced {category}: {log.records_inserted} inserted, "
                  f"{log.records_updated} updated.", "success")
        else:
            flash(f"Sync failed for {category}. Check sync logs.", "danger")

    return redirect(url_for("admin.sync"))


@admin_bp.route("/sync/<int:log_id>")
@login_required
@admin_required
def sync_detail(log_id):
    log = SyncLog.query.get_or_404(log_id)
    return render_template("admin/sync_detail.html", log=log)


# ── Scheduler ─────────────────────────────────────────────────────────────────

@admin_bp.route("/scheduler/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_scheduler():
    enabled = AppSetting.get("scheduler_enabled", "false") == "true"
    new_state = not enabled

    AppSetting.set("scheduler_enabled", "true" if new_state else "false",
                   "Whether the auto-sync scheduler is running")

    if new_state:
        interval = int(AppSetting.get("sync_interval_hours", "24"))
        from app.services.sync import run_full_sync
        app = current_app._get_current_object()
        if not scheduler.running:
            scheduler.start()
        try:
            scheduler.remove_job("nfl_full_sync")
        except APJobLookupError:
            pass  # job didn't exist yet — that's fine
        scheduler.add_job(func=lambda: run_full_sync(app), trigger="interval",
                          hours=interval, id="nfl_full_sync", replace_existing=True)
        flash(f"Scheduler started — syncing every {interval}h.", "success")
        logger.info("Scheduler enabled", extra={"interval_hours": interval})
    else:
        try:
            scheduler.remove_job("nfl_full_sync")
        except APJobLookupError:
            pass  # job didn't exist yet — that's fine
        flash("Scheduler stopped.", "info")
        logger.info("Scheduler disabled")

    return redirect(url_for("admin.index"))


@admin_bp.route("/scheduler/interval", methods=["POST"])
@login_required
@admin_required
def set_interval():
    hours = request.form.get("hours", 24, type=int)
    hours = max(1, min(hours, 168))  # 1h - 1 week
    AppSetting.set("sync_interval_hours", str(hours), "Sync interval in hours")
    flash(f"Sync interval set to {hours} hours.", "success")
    return redirect(url_for("admin.index"))


# ── DB Health ─────────────────────────────────────────────────────────────────

@admin_bp.route("/db")
@login_required
@admin_required
def db_health():
    stats = db_manager.get_db_stats()
    return render_template("admin/db_health.html", stats=stats)


@admin_bp.route("/db/audit")
@login_required
@admin_required
def db_audit():
    from app.services import db_audit as audit_svc
    findings = audit_svc.run_audit()
    total_issues = (
        len(findings["duplicate_teams"])
        + len(findings["duplicate_players"])
        + len(findings["duplicate_games"])
        + len(findings["duplicate_odds"])
        + len(findings["duplicate_news"])
    )
    return render_template("admin/db_audit.html", findings=findings, total_issues=total_issues)


@admin_bp.route("/db/cleanup", methods=["POST"])
@login_required
@admin_required
def db_cleanup():
    from app.services import db_audit as audit_svc
    action = request.form.get("action", "")
    try:
        if action == "fix_odds":
            n = audit_svc.fix_duplicate_odds()
            flash(f"Removed {n} duplicate odds row(s).", "success")
        elif action == "fix_games":
            n = audit_svc.fix_duplicate_games()
            flash(f"Merged and removed {n} duplicate game record(s).", "success")
        elif action == "fix_news":
            n = audit_svc.fix_duplicate_news()
            flash(f"Removed {n} duplicate news article(s).", "success")
        elif action == "fix_players":
            n = audit_svc.fix_duplicate_players()
            flash(f"Merged and removed {n} duplicate player record(s).", "success")
        else:
            flash(f"Unknown cleanup action: {action}", "danger")
    except Exception as exc:
        logger.error("DB cleanup failed", extra={"action": action, "error": str(exc)}, exc_info=True)
        flash(f"Cleanup failed: {exc}", "danger")
    return redirect(url_for("admin.db_audit"))


@admin_bp.route("/db/sql", methods=["POST"])
@login_required
@admin_required
def run_sql():
    sql = request.form.get("sql", "").strip()
    if not sql:
        return jsonify({"error": "No SQL provided"})
    try:
        results = db_manager.execute_sql(sql)
        logger.warning("Admin ran raw SQL", extra={"admin_id": current_user.id, "sql": sql[:200]})
        return jsonify({"results": results, "count": len(results)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# ── Log Viewer ────────────────────────────────────────────────────────────────

@admin_bp.route("/logs")
@login_required
@admin_required
def logs():
    log_dir = current_app.config.get("LOG_DIR", "/app/logs")
    log_files = []
    if os.path.exists(log_dir):
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
    return render_template("admin/logs.html", log_files=sorted(log_files))


@admin_bp.route("/logs/<log_file>")
@login_required
@admin_required
def view_log(log_file):
    log_dir = current_app.config.get("LOG_DIR", "/app/logs")
    # Sanitize — only allow .log files from the log dir
    if not log_file.endswith(".log") or "/" in log_file or ".." in log_file:
        flash("Invalid log file.", "danger")
        return redirect(url_for("admin.logs"))
    log_path = os.path.join(log_dir, log_file)
    if not os.path.exists(log_path):
        flash("Log file not found.", "warning")
        return redirect(url_for("admin.logs"))
    lines_param = request.args.get("lines", 200, type=int)
    # Read last N lines
    with open(log_path, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    recent = all_lines[-lines_param:]
    return render_template("admin/log_viewer.html", log_file=log_file,
                           lines=recent, total_lines=len(all_lines))
