"""
Reusable Flask decorators:
- role_required: enforce admin/user roles
- handle_errors: catch NFLTrackerException and return JSON or flash
"""
import logging
import functools
from flask import jsonify, flash, redirect, url_for, request
from flask_login import current_user
from app.exceptions import RoleRequiredException, LoginRequiredException, NFLTrackerException

logger = logging.getLogger("nfl.app")


def role_required(*roles: str):
    """Decorator that checks the current user has one of the given roles."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                raise LoginRequiredException("Login required",
                                             detail={"path": request.path})
            if current_user.role.value not in roles:
                raise RoleRequiredException(
                    f"Role '{current_user.role.value}' is not permitted here. "
                    f"Required: {roles}",
                    detail={"user_role": current_user.role.value, "required_roles": list(roles)},
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(fn):
    """Shorthand for role_required('admin')."""
    return role_required("admin")(fn)


def handle_errors(fn):
    """
    Catch NFLTrackerException in a route and return JSON or flash+redirect.
    For API routes returns JSON; for HTML routes flashes and redirects back.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NFLTrackerException as exc:
            logger.error(
                "Handled error in %s: %s", fn.__name__, exc.message,
                extra=exc.detail, exc_info=True,
            )
            if request.path.startswith("/api/"):
                return jsonify(exc.to_dict()), exc.status_code
            flash(exc.message, "danger")
            return redirect(request.referrer or url_for("dashboard.index"))
    return wrapper
