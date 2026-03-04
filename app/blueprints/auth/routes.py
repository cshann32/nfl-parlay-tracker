import logging
from datetime import datetime, timezone
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.blueprints.auth import auth_bp
from app.extensions import db
from app.models.user import User, UserRole
from app.exceptions import ValidationException

_LOGIN_LIMIT = 10       # max attempts
_LOGIN_WINDOW = 900     # 15 minutes in seconds


def _login_rate_key(ip: str) -> str:
    return f"login_attempts:{ip}"


def _is_rate_limited(ip: str) -> bool:
    """Return True if this IP has exceeded the login attempt limit."""
    try:
        from app.extensions import get_redis
        r = get_redis()
        attempts = r.get(_login_rate_key(ip))
        return attempts is not None and int(attempts) >= _LOGIN_LIMIT
    except Exception:
        return False  # fail open — don't block users if Redis is unavailable


def _record_failed_attempt(ip: str) -> None:
    try:
        from app.extensions import get_redis
        r = get_redis()
        key = _login_rate_key(ip)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOGIN_WINDOW)
        pipe.execute()
    except Exception:
        pass


def _clear_attempts(ip: str) -> None:
    try:
        from app.extensions import get_redis
        get_redis().delete(_login_rate_key(ip))
    except Exception:
        pass

logger = logging.getLogger("nfl.auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if _is_rate_limited(ip):
            logger.warning("Login rate limit exceeded", extra={"ip": ip})
            flash("Too many login attempts. Please wait 15 minutes before trying again.", "danger")
            return render_template("auth/login.html")

        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            _clear_attempts(ip)
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            logger.info("User logged in", extra={"user_id": user.id, "username": username})
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard.index"))
        _record_failed_attempt(ip)
        logger.warning("Failed login attempt",
                       extra={"username": username, "ip": ip,
                              "ua": request.headers.get("User-Agent", "")[:120]})
        flash("Invalid username or password.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("auth/register.html")
        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "danger")
            return render_template("auth/register.html")
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return render_template("auth/register.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("auth/register.html")

        # First user becomes admin
        role = UserRole.ADMIN if User.query.count() == 0 else UserRole.USER
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("New user registered", extra={"user_id": user.id, "role": role.value})
        flash("Account created! Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logger.info("User logged out", extra={"user_id": current_user.id})
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        current_pw = request.form.get("current_password", "")
        if not current_user.check_password(current_pw):
            flash("Current password is incorrect.", "danger")
        elif new_password != confirm:
            flash("New passwords do not match.", "danger")
        elif len(new_password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash("Password updated successfully.", "success")
    return render_template("auth/profile.html")
