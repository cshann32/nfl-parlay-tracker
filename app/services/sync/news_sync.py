"""Sync NFL news articles."""
import logging
from datetime import datetime, timezone
from app.extensions import db
from app.models.news import News
from .nfl_api_client import NFLApiClient

logger = logging.getLogger("nfl.sync.news")

NEWS_PATHS = ["/nfl-news/v1/data", "/news", "/v1/news"]


def sync_news(client: NFLApiClient) -> tuple[int, int, int]:
    inserted = updated = skipped = 0
    for path in NEWS_PATHS:
        try:
            raw = client.get(path)
            articles = _extract(raw)
            for a in articles:
                i, u, s = _upsert(a)
                inserted += i; updated += u; skipped += s
            break
        except Exception:
            continue

    db.session.commit()
    logger.info("News sync complete",
                extra={"inserted": inserted, "updated": updated, "skipped": skipped})
    return inserted, updated, skipped


def _upsert(raw: dict) -> tuple[int, int, int]:
    api_id = str(raw.get("id") or raw.get("headline") or "")[:200]
    if not api_id:
        return 0, 0, 1
    n = News.query.filter_by(api_id=api_id).first()
    is_new = n is None
    if is_new:
        n = News(api_id=api_id); db.session.add(n)
    n.headline = raw.get("headline") or raw.get("title") or n.headline or ""
    n.description = raw.get("description") or raw.get("story") or n.description
    n.link = raw.get("links", {}).get("web", {}).get("href") or raw.get("url") or n.link
    # Try common image field names used by various NFL APIs
    n.image_url = (
        raw.get("image_url") or raw.get("imageUrl") or raw.get("thumbnail") or
        raw.get("img") or raw.get("photo") or
        (raw.get("image", {}) or {}).get("url") or
        (raw.get("images", [{}]) or [{}])[0].get("url") or
        n.image_url
    )
    pub = raw.get("published") or raw.get("publishedAt")
    if pub:
        try:
            n.published_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            pass
    return (1, 0, 0) if is_new else (0, 1, 0)


def _extract(data) -> list:
    if isinstance(data, list): return data
    for k in ["articles", "news", "data", "results"]:
        if isinstance(data.get(k) if isinstance(data, dict) else None, list):
            return data[k]
    return []
