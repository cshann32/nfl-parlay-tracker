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
    # ── The Odds API ─────────────────────────────────
    "the_odds_api",
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
    last_odds_sync = (
        SyncLog.query
        .filter_by(category="the_odds_api")
        .filter(SyncLog.status == SyncStatus.SUCCESS)
        .order_by(SyncLog.finished_at.desc())
        .first()
    )
    return render_template(
        "admin/sync.html",
        recent=recent,
        categories=VALID_SYNC_CATEGORIES,
        last_odds_sync=last_odds_sync,
    )


@admin_bp.route("/sync/run", methods=["POST"])
@login_required
@admin_required
def run_sync():
    category = request.form.get("category", "all")
    if category not in VALID_SYNC_CATEGORIES:
        flash(f"Invalid category: {category}", "danger")
        return redirect(url_for("admin.sync"))

    # ESPN-based syncs use the free public API — no key required
    ESPN_FREE = {"game_stats", "espn_odds", "espn_teams", "espn_roster", "espn_schedule", "espn_news", "the_odds_api"}
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
        from app.services.sync import run_full_sync, run_weekly_stats_sync
        app = current_app._get_current_object()
        if not scheduler.running:
            scheduler.start()
        for job_id in ("nfl_full_sync", "weekly_stats_sync"):
            try:
                scheduler.remove_job(job_id)
            except APJobLookupError:
                pass
        scheduler.add_job(func=lambda: run_full_sync(app), trigger="interval",
                          hours=interval, id="nfl_full_sync", replace_existing=True)
        scheduler.add_job(func=lambda: run_weekly_stats_sync(app),
                          trigger="cron", day_of_week="sun", hour=23, minute=0,
                          timezone="America/New_York",
                          id="weekly_stats_sync", replace_existing=True)
        flash(f"Scheduler started — full sync every {interval}h + stats every Sunday 11 PM ET.", "success")
        logger.info("Scheduler enabled", extra={"interval_hours": interval})
    else:
        for job_id in ("nfl_full_sync", "weekly_stats_sync"):
            try:
                scheduler.remove_job(job_id)
            except APJobLookupError:
                pass
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


# ── Settings ─────────────────────────────────────────────────────────────────
#
# Each setting dict:
#   key, label, type, default, desc, config_key (optional), sensitive (bool)
#
# type: "int" | "text" | "bool" | "secret" | "select:<opt1>|<opt2>|..."
# config_key: app.config key to update at runtime (None = AppSetting only)

SETTINGS_GROUPS = [
    {
        "id": "app", "title": "Application", "icon": "bi-gear-fill", "color": "#94a3b8",
        "settings": [
            {"key": "current_season_year",   "label": "Current Season Year",
             "type": "int",    "default": "2025", "config_key": "CURRENT_SEASON",
             "desc": "Season year used for default queries, stats pages and dashboard"},
            {"key": "log_level",             "label": "Log Level",
             "type": "select:DEBUG|INFO|WARNING|ERROR|CRITICAL",
             "default": "INFO", "config_key": "LOG_LEVEL",
             "desc": "Application log verbosity — DEBUG is verbose, INFO is standard"},
            {"key": "session_cookie_secure", "label": "Secure Cookie (HTTPS only)",
             "type": "bool",   "default": "true", "config_key": "SESSION_COOKIE_SECURE",
             "desc": "Set false only if running over plain HTTP (local LAN without SSL)"},
        ],
    },
    {
        "id": "uploads", "title": "File Uploads", "icon": "bi-cloud-upload-fill", "color": "#fb923c",
        "settings": [
            {"key": "max_upload_size_mb",    "label": "Max Upload Size (MB)",
             "type": "int",    "default": "50",  "config_key": None,
             "desc": "Maximum size of a single uploaded file"},
            {"key": "allowed_extensions",    "label": "Allowed File Types",
             "type": "text",   "default": "pdf,csv,xlsx,xls,png,jpg,jpeg,gif,tiff,bmp,json,xml",
             "config_key": None,
             "desc": "Comma-separated list of allowed upload extensions (no dots)"},
        ],
    },
    {
        "id": "scheduler", "title": "Sync & Scheduler", "icon": "bi-arrow-repeat", "color": "#4ade80",
        "settings": [
            {"key": "scheduler_enabled",     "label": "Auto-Sync Enabled",
             "type": "bool",   "default": "false", "config_key": "SCHEDULER_ENABLED",
             "desc": "Enable the background sync scheduler (toggle from Admin home also works)"},
            {"key": "sync_interval_hours",   "label": "Full Sync Interval (hours)",
             "type": "int",    "default": "24",  "config_key": "SYNC_INTERVAL_HOURS",
             "desc": "How often the full NFL data sync runs when scheduler is on"},
            {"key": "weekly_sync_day",       "label": "Weekly Stats Sync Day",
             "type": "select:mon|tue|wed|thu|fri|sat|sun",
             "default": "sun", "config_key": None,
             "desc": "Day of week to run the automatic stats + settle job"},
            {"key": "weekly_sync_hour",      "label": "Weekly Stats Sync Hour (0–23)",
             "type": "int",    "default": "23",  "config_key": None,
             "desc": "Hour of day (24h, local server time) to run the weekly stats sync"},
        ],
    },
    {
        "id": "nfl_api", "title": "NFL API (RapidAPI)", "icon": "bi-key-fill", "color": "#60a5fa",
        "settings": [
            {"key": "nfl_api_key",           "label": "NFL API Key",
             "type": "secret", "default": "", "config_key": "NFL_API_KEY", "sensitive": True,
             "desc": "RapidAPI key — required for games, stats, boxscores, plays, and draft sync"},
            {"key": "nfl_api_host_primary",  "label": "Primary API Host",
             "type": "text",   "default": "nfl-football-api.p.rapidapi.com",
             "config_key": "NFL_API_HOST_PRIMARY",
             "desc": "Primary RapidAPI host for NFL data"},
            {"key": "nfl_api_host_fallback", "label": "Fallback API Host",
             "type": "text",   "default": "nfl-api-data.p.rapidapi.com",
             "config_key": "NFL_API_HOST_FALLBACK",
             "desc": "Fallback host used if the primary fails"},
            {"key": "nfl_api_timeout",       "label": "Request Timeout (seconds)",
             "type": "int",    "default": "30", "config_key": "NFL_API_TIMEOUT",
             "desc": "Seconds before a RapidAPI request is abandoned"},
            {"key": "nfl_api_retry_count",   "label": "Max Retries",
             "type": "int",    "default": "3",  "config_key": "NFL_API_RETRY_COUNT",
             "desc": "How many times to retry a failed request before giving up"},
        ],
    },
    {
        "id": "odds_api", "title": "The Odds API", "icon": "bi-graph-up-arrow", "color": "#a78bfa",
        "settings": [
            {"key": "the_odds_api_key",           "label": "The Odds API Key",
             "type": "secret", "default": "", "config_key": "THE_ODDS_API_KEY", "sensitive": True,
             "desc": "Free plan: 500 credits/month · 3 credits per odds sync"},
            {"key": "the_odds_api_cooldown_hours","label": "Sync Cooldown (hours)",
             "type": "int",    "default": "4",  "config_key": None,
             "desc": "Minimum hours between odds syncs to protect monthly credit quota"},
        ],
    },
    {
        "id": "commissioner", "title": "The Commissioner", "icon": "bi-shield-fill-check", "color": "#69BE28",
        "settings": [
            {"key": "commissioner_stuck_hours",      "label": "Stuck Leg Threshold (hours)",
             "type": "int",    "default": "24",
             "desc": "Flag PENDING parlay legs after their game has been Final for N hours"},
            {"key": "commissioner_odds_stale_hours", "label": "Odds Freshness Window (hours)",
             "type": "int",    "default": "48",
             "desc": "Flag upcoming games whose odds haven't been refreshed in N hours"},
            {"key": "commissioner_score_max",        "label": "Max Combined Score",
             "type": "int",    "default": "100",
             "desc": "Flag games with combined score above this — catches Pro Bowl outliers"},
        ],
    },
]


def _all_settings_flat():
    for group in SETTINGS_GROUPS:
        for s in group["settings"]:
            yield s


def _read_all_values() -> dict[str, str]:
    """Current effective value for every setting (AppSetting overrides app.config/default)."""
    stored = {r.key: r.value for r in AppSetting.query.all()}
    out = {}
    for s in _all_settings_flat():
        key = s["key"]
        if key in stored:
            out[key] = stored[key]
        elif s.get("config_key"):
            out[key] = str(current_app.config.get(s["config_key"], s["default"]))
        else:
            out[key] = s["default"]
    return out


def _apply_side_effects(key: str, val: str) -> None:
    """Extra runtime actions for settings that affect more than just app.config."""
    import logging as _logging
    if key == "log_level":
        level = getattr(_logging, val.upper(), _logging.INFO)
        _logging.getLogger("nfl").setLevel(level)
        _logging.getLogger().setLevel(level)

    elif key == "max_upload_size_mb":
        current_app.config["MAX_CONTENT_LENGTH"] = int(val) * 1024 * 1024

    elif key == "allowed_extensions":
        exts = {e.strip().lower() for e in val.split(",") if e.strip()}
        current_app.config["ALLOWED_EXTENSIONS"] = exts

    elif key == "session_cookie_secure":
        current_app.config["SESSION_COOKIE_SECURE"] = (val == "true")

    elif key in ("weekly_sync_day", "weekly_sync_hour"):
        # Reschedule the weekly stats job if the scheduler is running
        try:
            from apscheduler.jobstores.base import JobLookupError as _JLE
            from app.services.sync import run_weekly_stats_sync
            _app = current_app._get_current_object()
            day  = AppSetting.get("weekly_sync_day",  "sun")
            hour = int(AppSetting.get("weekly_sync_hour", "23"))
            if scheduler.running:
                try:
                    scheduler.remove_job("weekly_stats_sync")
                except _JLE:
                    pass
                scheduler.add_job(
                    func=lambda: run_weekly_stats_sync(_app),
                    trigger="cron", day_of_week=day, hour=hour, minute=0,
                    timezone="America/New_York",
                    id="weekly_stats_sync", replace_existing=True,
                )
        except Exception as exc:
            logger.warning("Could not reschedule weekly sync: %s", exc)


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        updated = 0
        for s in _all_settings_flat():
            key  = s["key"]
            kind = s["type"].split(":")[0]
            sensitive = s.get("sensitive", False)
            val = request.form.get(key, "").strip()

            if sensitive and not val:
                continue  # blank secret = keep existing
            if not val:
                val = s["default"]
            if kind == "int":
                try:
                    int(val)
                except ValueError:
                    flash(f"{s['label']}: must be a number — skipped.", "warning")
                    continue

            AppSetting.set(key, val, s["desc"])

            if s.get("config_key"):
                cfg_key = s["config_key"]
                if kind == "int":
                    current_app.config[cfg_key] = int(val)
                elif kind == "bool":
                    current_app.config[cfg_key] = (val == "true")
                else:
                    current_app.config[cfg_key] = val

            _apply_side_effects(key, val)
            updated += 1

        flash(f"{updated} setting(s) saved and applied immediately.", "success")
        logger.info("Settings updated", extra={"by": current_user.username, "count": updated})
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html",
                           groups=SETTINGS_GROUPS,
                           values=_read_all_values(),
                           config=current_app.config)


# ── API Tester ────────────────────────────────────────────────────────────────

@admin_bp.route("/api-tester")
@login_required
@admin_required
def api_tester():
    from app.models.app_setting import AppSetting
    def _masked(val):
        if val and val not in ("", "your-rapidapi-key-here", "your-the-odds-api-key-here"):
            return val[:8] + "••••••••"
        return None

    nfl_key   = AppSetting.get("nfl_api_key")   or current_app.config.get("NFL_API_KEY", "")
    odds_key  = AppSetting.get("the_odds_api_key") or current_app.config.get("THE_ODDS_API_KEY", "")
    return render_template("admin/api_tester.html",
                           nfl_key_masked=_masked(nfl_key),
                           odds_key_masked=_masked(odds_key))


@admin_bp.route("/api-tester/test/<provider>", methods=["POST"])
@login_required
@admin_required
def api_tester_test(provider):
    import time, requests as _req
    from app.models.app_setting import AppSetting

    trial_key = request.form.get("key", "").strip()

    if provider == "nfl":
        key = trial_key or AppSetting.get("nfl_api_key") or current_app.config.get("NFL_API_KEY", "")
        if not key:
            return jsonify({"ok": False, "message": "No NFL API key configured."})
        primary  = AppSetting.get("nfl_api_host_primary")  or current_app.config.get("NFL_API_HOST_PRIMARY",  "nfl-football-api.p.rapidapi.com")
        fallback = AppSetting.get("nfl_api_host_fallback") or current_app.config.get("NFL_API_HOST_FALLBACK", "nfl-api-data.p.rapidapi.com")
        # Probe both hosts with the known-good teams endpoint used by the sync
        test_path = "/nfl-team-listing/v1/data"
        t0 = time.monotonic()
        connected_host = None
        last_status = None
        for host in [primary, fallback]:
            try:
                r = _req.get(f"https://{host}{test_path}",
                             headers={"x-rapidapi-host": host, "x-rapidapi-key": key},
                             timeout=10)
                last_status = r.status_code
                if r.status_code == 200:
                    connected_host = host
                    resp = r
                    break
                if r.status_code in (401, 403):
                    ms = round((time.monotonic() - t0) * 1000)
                    msg = "Invalid API key." if r.status_code == 401 else "Forbidden — key inactive or quota exceeded."
                    return jsonify({"ok": False, "status": r.status_code, "message": msg, "ms": ms})
            except Exception:
                continue
        ms = round((time.monotonic() - t0) * 1000)
        if not connected_host:
            return jsonify({"ok": False, "status": last_status, "message": "Both hosts returned errors — check key and hosts in Settings.", "ms": ms})
        try:
            data = resp.json()
            count = len(data) if isinstance(data, list) else len(data.get("teams", data.get("data", [])))
            return jsonify({"ok": True, "status": 200, "message": f"Connected — {count} teams returned.", "ms": ms, "host": connected_host})
        except Exception as exc:
            return jsonify({"ok": False, "message": f"Connection error: {exc}"})

    elif provider == "odds":
        key = trial_key or AppSetting.get("the_odds_api_key") or current_app.config.get("THE_ODDS_API_KEY", "")
        if not key:
            return jsonify({"ok": False, "message": "No Odds API key configured."})
        # /v4/sports lists all sports — costs 0 credits and confirms the key is valid
        url = "https://api.the-odds-api.com/v4/sports"
        t0 = time.monotonic()
        try:
            resp = _req.get(url, params={"apiKey": key}, timeout=10)
            ms = round((time.monotonic() - t0) * 1000)
            if resp.status_code == 401:
                return jsonify({"ok": False, "status": 401, "message": "Invalid API key.", "ms": ms})
            if not resp.ok:
                return jsonify({"ok": False, "status": resp.status_code, "message": f"API returned {resp.status_code}.", "ms": ms})
            remaining = resp.headers.get("x-requests-remaining", "?")
            used      = resp.headers.get("x-requests-used", "?")
            sports = resp.json()
            nfl = next((s for s in sports if "americanfootball_nfl" in s.get("key", "")), None)
            active = nfl.get("active", False) if nfl else False
            return jsonify({
                "ok": True, "status": 200, "ms": ms,
                "message": f"Connected — NFL {'in season' if active else 'off season'} · {len(sports)} sports available.",
                "credits_remaining": remaining,
                "credits_used": used,
            })
        except Exception as exc:
            return jsonify({"ok": False, "message": f"Connection error: {exc}"})

    elif provider == "espn":
        endpoint = request.form.get("endpoint", "scoreboard")
        urls = {
            "scoreboard": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?limit=1",
            "summary":    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=401671889",
            "roster":     "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/29/roster",
        }
        url = urls.get(endpoint, urls["scoreboard"])
        t0 = time.monotonic()
        try:
            resp = _req.get(url, headers={"User-Agent": "NFL-Parlay-Tracker/1.0"}, timeout=10)
            ms = round((time.monotonic() - t0) * 1000)
            if not resp.ok:
                return jsonify({"ok": False, "status": resp.status_code, "message": f"ESPN returned {resp.status_code}.", "ms": ms})
            return jsonify({"ok": True, "status": 200, "ms": ms,
                            "message": f"ESPN {endpoint} API reachable.",
                            "content_length": len(resp.content)})
        except Exception as exc:
            return jsonify({"ok": False, "message": f"Connection error: {exc}"})

    return jsonify({"ok": False, "message": f"Unknown provider: {provider}"})


@admin_bp.route("/api-tester/save-key/<provider>", methods=["POST"])
@login_required
@admin_required
def api_tester_save_key(provider):
    key = request.form.get("key", "").strip()
    if not key:
        flash("No key provided.", "warning")
        return redirect(url_for("admin.api_tester"))

    if provider == "nfl":
        AppSetting.set("nfl_api_key", key, "NFL RapidAPI key")
        current_app.config["NFL_API_KEY"] = key
        flash("NFL API key saved and active.", "success")
        logger.info("NFL API key replaced", extra={"by": current_user.username})
    elif provider == "odds":
        AppSetting.set("the_odds_api_key", key, "The Odds API key")
        current_app.config["THE_ODDS_API_KEY"] = key
        flash("Odds API key saved and active.", "success")
        logger.info("Odds API key replaced", extra={"by": current_user.username})
    else:
        flash(f"Unknown provider: {provider}", "danger")

    return redirect(url_for("admin.api_tester"))


# ── The Commissioner ──────────────────────────────────────────────────────────

@admin_bp.route("/commissioner")
@login_required
@admin_required
def commissioner():
    import json
    from app.services.commissioner import seed_settings
    from app.models.app_setting import AppSetting
    seed_settings()
    raw = AppSetting.get("commissioner_last_run")
    last_run = json.loads(raw) if raw else None
    settings = {
        "stuck_hours":      AppSetting.get("commissioner_stuck_hours", "24"),
        "odds_stale_hours": AppSetting.get("commissioner_odds_stale_hours", "48"),
        "score_max":        AppSetting.get("commissioner_score_max", "100"),
    }
    return render_template("admin/commissioner.html",
                           last_run=last_run, settings=settings)


@admin_bp.route("/commissioner/run", methods=["POST"])
@login_required
@admin_required
def commissioner_run():
    from app.services.commissioner import run_commissioner
    run = run_commissioner(triggered_by=f"admin:{current_user.username}")
    fixed   = run["total_fixed"]
    warnings = run["warnings"]
    errors   = run["errors"]
    if errors:
        flash(f"Commissioner: {fixed} rows fixed — {warnings} warning(s), {errors} error(s) need attention.", "warning")
    elif warnings:
        flash(f"Commissioner: {fixed} rows fixed — {warnings} item(s) need your attention.", "info")
    else:
        flash(f"Commissioner: all clean. {fixed} rows fixed.", "success")
    return redirect(url_for("admin.commissioner"))




# ── DB Health ─────────────────────────────────────────────────────────────────

@admin_bp.route("/db")
@login_required
@admin_required
def db_health():
    stats = db_manager.get_db_stats()
    return render_template("admin/db_health.html", stats=stats)




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
