"""
Flask extension instances.
Initialised here, bound to the app in create_app() via init_app().
"""
import redis as redis_lib
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect
from apscheduler.schedulers.background import BackgroundScheduler

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()
csrf = CSRFProtect()
scheduler = BackgroundScheduler()

# Redis client — initialised in create_app after config is loaded
redis_client: redis_lib.Redis | None = None


def init_redis(app) -> None:
    global redis_client
    redis_client = redis_lib.from_url(
        app.config["REDIS_URL"],
        decode_responses=True,
    )


def get_redis() -> redis_lib.Redis:
    if redis_client is None:
        raise RuntimeError("Redis not initialised — call init_redis(app) first")
    return redis_client
