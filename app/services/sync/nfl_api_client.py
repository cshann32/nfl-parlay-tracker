"""
NFL API HTTP client.
Handles authentication, retries, rate limiting, and full request/response logging.
Never called by the Flask app at runtime — only by sync service.
"""
import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.exceptions import (
    APIConnectionException,
    APIRateLimitException,
    APIResponseException,
)

logger = logging.getLogger("nfl.sync")

# Known working endpoint paths per host — discovered at runtime
_PRIMARY_HOST = "nfl-football-api.p.rapidapi.com"
_FALLBACK_HOST = "nfl-api-data.p.rapidapi.com"


class NFLApiClient:
    """
    RapidAPI NFL client with:
    - Primary + fallback host support
    - Automatic 3x exponential backoff retry
    - 429 rate-limit detection and wait
    - Full structured logging of every call
    """

    def __init__(self, api_key: str, primary_host: str = _PRIMARY_HOST,
                 fallback_host: str = _FALLBACK_HOST, timeout: int = 30,
                 max_retries: int = 3):
        if not api_key:
            raise ValueError("NFL_API_KEY is not set — check your .env file")
        self.api_key = api_key
        self.primary_host = primary_host
        self.fallback_host = fallback_host
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.max_retries,
            backoff_factor=1,         # 1s, 2s, 4s waits between retries
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        return session

    def _headers(self, host: str) -> dict:
        return {
            "x-rapidapi-host": host,
            "x-rapidapi-key": self.api_key,
        }

    def get(self, path: str, params: dict | None = None) -> Any:
        """
        Make a GET request, trying primary host first then fallback.
        Returns parsed JSON or raises a SyncException subclass.
        """
        for host in [self.primary_host, self.fallback_host]:
            url = f"https://{host}{path}"
            try:
                result = self._request(url, host, params or {})
                return result
            except APIResponseException as e:
                if "404" in str(e.detail.get("status_code", "")):
                    logger.warning(
                        "Endpoint not found on host, trying fallback",
                        extra={"host": host, "path": path},
                    )
                    continue   # Try next host
                raise
        raise APIResponseException(
            f"Endpoint {path} not found on either host",
            detail={"path": path, "primary": self.primary_host, "fallback": self.fallback_host},
        )

    def _request(self, url: str, host: str, params: dict) -> Any:
        start = time.monotonic()
        logger.info("API request", extra={"url": url, "params": params, "host": host})
        try:
            resp = self._session.get(
                url, headers=self._headers(host), params=params, timeout=self.timeout
            )
        except requests.exceptions.ConnectionError as exc:
            raise APIConnectionException(
                f"Connection failed: {url}",
                detail={"url": url, "error": str(exc)},
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise APIConnectionException(
                f"Request timed out after {self.timeout}s: {url}",
                detail={"url": url, "timeout": self.timeout},
            ) from exc

        duration_ms = round((time.monotonic() - start) * 1000, 1)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            logger.warning(
                "Rate limited — waiting",
                extra={"url": url, "retry_after": retry_after},
            )
            time.sleep(retry_after)
            raise APIRateLimitException(
                "Rate limit hit on NFL API",
                detail={"url": url, "retry_after": retry_after},
            )

        if resp.status_code == 404:
            raise APIResponseException(
                f"404 Not Found: {url}",
                detail={"url": url, "status_code": 404},
            )

        if not resp.ok:
            logger.error(
                "API error response",
                extra={"url": url, "status_code": resp.status_code, "body": resp.text[:500]},
            )
            raise APIResponseException(
                f"API returned {resp.status_code}: {url}",
                detail={"url": url, "status_code": resp.status_code, "body": resp.text[:500]},
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise APIResponseException(
                "API returned non-JSON response",
                detail={"url": url, "body": resp.text[:500]},
            ) from exc

        record_count = _estimate_count(data)
        logger.info(
            "API response received",
            extra={
                "url": url,
                "status_code": resp.status_code,
                "duration_ms": duration_ms,
                "estimated_records": record_count,
            },
        )
        return data


def _estimate_count(data: Any) -> int:
    """Best-effort count of records in an API response."""
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("results", "data", "athletes", "teams", "events", "games",
                    "players", "items", "records"):
            if isinstance(data.get(key), list):
                return len(data[key])
    return 1
