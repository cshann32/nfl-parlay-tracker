"""
Seed 2025 NFL season player stats from ESPN's free public API.
Run with: python seed_stats_2025.py
"""
import time
import requests
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.stat import PlayerStat

app = create_app()

SEASON = 2025
# type 2 = regular season
ESPN_STATS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/seasons/{season}/types/2/athletes/{espn_id}/statistics/0"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NFLTracker/1.0)"}

# Only fetch stats for positions likely to have meaningful data
STAT_POSITIONS = {
    "QB", "RB", "FB", "WR", "TE", "K", "P",
    "DE", "DT", "NT", "LB", "OLB", "ILB", "MLB",
    "CB", "S", "SS", "FS", "DB",
}


def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def upsert_stat(player_id, stat_category, stat_type, value, season_year):
    existing = PlayerStat.query.filter_by(
        player_id=player_id,
        game_id=None,
        stat_category=stat_category,
        stat_type=stat_type,
        season_year=season_year,
    ).first()
    if existing:
        existing.value = value
        return False
    db.session.add(PlayerStat(
        player_id=player_id,
        game_id=None,
        season_year=season_year,
        week=None,
        stat_category=stat_category,
        stat_type=stat_type,
        value=value,
    ))
    return True


def seed_player_stats():
    players = Player.query.filter(
        Player.api_id.like("espn_%"),
        Player.position.in_(STAT_POSITIONS),
    ).all()

    print(f"Fetching 2025 season stats for {len(players)} players...")
    print("(Only positions: QB/RB/WR/TE/K/P/DL/LB/DB)\n")

    total_inserted = total_updated = skipped = 0
    batch_size = 50

    for i, player in enumerate(players, 1):
        espn_id = player.api_id.replace("espn_", "")
        url = ESPN_STATS_URL.format(season=SEASON, espn_id=espn_id)
        data = get_json(url)

        if not data:
            skipped += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(players)}] {skipped} skipped so far...")
            time.sleep(0.05)
            continue

        categories = data.get("splits", {}).get("categories", [])
        inserted = updated = 0

        for cat in categories:
            cat_name = cat.get("name", "general").lower()
            for stat in cat.get("stats", []):
                stat_name = stat.get("abbreviation") or stat.get("name", "")
                raw_val = stat.get("value")
                if stat_name and raw_val is not None:
                    try:
                        val = float(raw_val)
                        if val == 0.0:
                            continue  # skip zero stats to keep DB lean
                        is_new = upsert_stat(
                            player.id, cat_name, stat_name, val, SEASON
                        )
                        if is_new:
                            inserted += 1
                        else:
                            updated += 1
                    except (ValueError, TypeError):
                        continue

        total_inserted += inserted
        total_updated += updated

        if inserted > 0 or updated > 0:
            print(f"  {player.name} ({player.position}): {inserted} new, {updated} updated")

        # Commit in batches
        if i % batch_size == 0:
            db.session.commit()
            print(f"  --- committed batch [{i}/{len(players)}] ---")

        time.sleep(0.1)  # polite rate limiting

    db.session.commit()
    print(f"\n=== Done ===")
    print(f"Players processed : {len(players)}")
    print(f"Players skipped   : {skipped} (no stats / not found)")
    print(f"Stats inserted    : {total_inserted}")
    print(f"Stats updated     : {total_updated}")


if __name__ == "__main__":
    with app.app_context():
        seed_player_stats()
