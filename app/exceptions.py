"""
Custom exception hierarchy for NFL Parlay Tracker.
Every exception carries a message and optional detail dict for structured logging.
"""


class NFLTrackerException(Exception):
    """Base exception for all app errors."""
    status_code = 500

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"error": self.__class__.__name__, "message": self.message, "detail": self.detail}


# ─── Database ─────────────────────────────────────────────────────────────────

class DatabaseException(NFLTrackerException):
    """Raised for DB connection, query, or constraint errors."""
    status_code = 500


# ─── Sync / API ───────────────────────────────────────────────────────────────

class SyncException(NFLTrackerException):
    """Base for all NFL API sync errors."""
    status_code = 502


class APIConnectionException(SyncException):
    """Network timeout or connection refused when calling the NFL API."""
    status_code = 503


class APIRateLimitException(SyncException):
    """HTTP 429 received from NFL API."""
    status_code = 429


class APIResponseException(SyncException):
    """Non-200 response or malformed JSON from NFL API."""
    status_code = 502


class DataMappingException(SyncException):
    """API response field missing or wrong type during DB write."""
    status_code = 500


# ─── Document Parsing ─────────────────────────────────────────────────────────

class ParseException(NFLTrackerException):
    """Base for all document parsing failures."""
    status_code = 422


class PDFParseException(ParseException):
    """Failure reading or extracting data from a PDF file."""


class CSVParseException(ParseException):
    """Failure reading or mapping a CSV/Excel file."""


class ImageParseException(ParseException):
    """Failure during OCR or image preprocessing."""


class JSONParseException(ParseException):
    """Failure parsing JSON or XML document."""


# ─── Auth ─────────────────────────────────────────────────────────────────────

class AuthException(NFLTrackerException):
    """Authentication or authorisation failure."""
    status_code = 403


class LoginRequiredException(AuthException):
    """User must be logged in."""
    status_code = 401


class RoleRequiredException(AuthException):
    """User lacks the required role."""
    status_code = 403


# ─── Validation ───────────────────────────────────────────────────────────────

class ValidationException(NFLTrackerException):
    """Form or input data failed validation."""
    status_code = 400


# ─── Reports ──────────────────────────────────────────────────────────────────

class ReportException(NFLTrackerException):
    """Report build or export failure."""
    status_code = 500
