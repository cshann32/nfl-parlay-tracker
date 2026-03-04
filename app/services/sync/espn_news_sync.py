"""
Sync NFL news from ESPN's free public site API.
No API key required.

Endpoint: GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/news
Returns the 50 most recent NFL news articles and upserts them into the news table.
"""
import logging
from datetime import datetime, timezone

import requests

from app.extensions import db
from app.models.news import News

logger = logging.getLogger("nfl.sync.espn_news")

ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
_HEADERS = {"User-Agent": "NFL-Parlay-Tracker/1.0"}


def sync_espn_news(client=None) -> tuple[int, int, int]:
    """
    Fetch the latest NFL news from ESPN and upsert into the news table.
    Returns (inserted, updated, skipped).
    """
    inserted = updated = skipped = 0

    resp = requests.get(ESPN_NEWS_URL, params={"limit": 50}, timeout=15, headers=_HEADERS)
    resp.raise_for_status()
    data = resp.json()

    articles = data.get("articles", [])
    if not articles:
        logger.warning("ESPN news API returned no articles")
        return 0, 0, 0

    for article in articles:
        # ESPN articles have either 'id' or 'dataSourceIdentifier'
        raw_id = str(
            article.get("id") or article.get("dataSourceIdentifier") or ""
        ).strip()
        if not raw_id:
            skipped += 1
            continue

        api_id   = f"espn_news_{raw_id}"
        headline = (article.get("headline") or "").strip()
        if not headline:
            skipped += 1
            continue

        description = (article.get("description") or "").strip() or None

        # Web link
        link = None
        links = article.get("links") or {}
        if isinstance(links, dict):
            web = links.get("web") or {}
            link = web.get("href") or None

        # Thumbnail / hero image
        images    = article.get("images") or []
        image_url = images[0].get("url") if images else None

        # Published date
        published_str = article.get("published") or ""
        published_at  = None
        if published_str:
            try:
                published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except Exception:
                pass

        existing = News.query.filter_by(api_id=api_id).first()
        if existing:
            existing.headline    = headline
            existing.description = description
            existing.link        = link or existing.link
            existing.image_url   = image_url or existing.image_url
            existing.synced_at   = datetime.now(timezone.utc)
            updated += 1
        else:
            db.session.add(News(
                api_id=api_id,
                headline=headline,
                description=description,
                link=link,
                image_url=image_url,
                published_at=published_at,
            ))
            inserted += 1

    db.session.commit()
    logger.info(
        "ESPN news sync complete",
        extra={"inserted": inserted, "updated": updated, "skipped": skipped},
    )
    return inserted, updated, skipped
