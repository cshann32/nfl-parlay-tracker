"""
Flask configuration classes.
All sensitive values are read from environment variables — never hardcoded.
"""
import os


CURRENT_SEASON: int = int(os.environ.get("CURRENT_SEASON", "2025"))


class BaseConfig:
    # ── Core ──────────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    DEBUG: bool = False
    TESTING: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "postgresql://nfl:nflpassword@localhost:5432/nfl_tracker"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_size": 10,
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }

    # ── Redis / Sessions ──────────────────────────────────────────────────────
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    SESSION_TYPE: str = "redis"
    SESSION_PERMANENT: bool = False
    SESSION_USE_SIGNER: bool = True

    # ── File Uploads ──────────────────────────────────────────────────────────
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "/app/uploads")
    MAX_CONTENT_LENGTH: int = int(os.environ.get("MAX_CONTENT_LENGTH", 52_428_800))
    ALLOWED_EXTENSIONS: set = {"pdf", "csv", "xlsx", "xls", "png", "jpg", "jpeg",
                                "gif", "tiff", "bmp", "json", "xml"}

    # ── NFL API ───────────────────────────────────────────────────────────────
    NFL_API_KEY: str = os.environ.get("NFL_API_KEY", "")
    NFL_API_HOST_PRIMARY: str = os.environ.get(
        "NFL_API_HOST_PRIMARY", "nfl-football-api.p.rapidapi.com"
    )
    NFL_API_HOST_FALLBACK: str = os.environ.get(
        "NFL_API_HOST_FALLBACK", "nfl-api-data.p.rapidapi.com"
    )
    NFL_API_TIMEOUT: int = int(os.environ.get("NFL_API_TIMEOUT", 30))
    NFL_API_RETRY_COUNT: int = int(os.environ.get("NFL_API_RETRY_COUNT", 3))

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.environ.get("LOG_DIR", "/app/logs")

    # ── Scheduler ─────────────────────────────────────────────────────────────
    SCHEDULER_ENABLED: bool = os.environ.get("SCHEDULER_ENABLED", "false").lower() == "true"
    SYNC_INTERVAL_HOURS: int = int(os.environ.get("SYNC_INTERVAL_HOURS", 24))
    SCHEDULER_API_ENABLED: bool = False  # Don't expose APScheduler REST API


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    LOG_LEVEL = "DEBUG"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 5,
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "echo": False,  # Set True to log all SQL statements
    }


class ProductionConfig(BaseConfig):
    DEBUG = False
    LOG_LEVEL = "INFO"
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    LOG_LEVEL = "DEBUG"


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config() -> type[BaseConfig]:
    env = os.environ.get("FLASK_ENV", "development")
    return CONFIG_MAP.get(env, DevelopmentConfig)
