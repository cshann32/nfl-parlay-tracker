"""
seed_all.py — Comprehensive NFL data seeder
Covers: rosters, venues, coaches, seasons, games (2024+2025),
        team stats (2024+2025), injuries, historical player stats (2022+2023)

All ESPN free public APIs — no API key required.
Run with: python seed_all.py
Re-running is safe — everything uses upsert logic.
"""
import time
import requests
from datetime import datetime, timezone, date
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models.team import Team
from app.models.player import Player
from app.models.venue import Venue
from app.models.coach import Coach
from app.models.season import Season
from app.models.game import Game
from app.models.stat import PlayerStat, TeamStat
from app.models.injury import Injury

app = create_app()

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NFLTracker/1.0)"}

# ── ESPN URLs ──────────────────────────────────────────────────────────────────
ESPN_TEAMS_URL        = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams?limit=32"
ESPN_ROSTER_URL       = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{espn_id}/roster"
ESPN_SEASON_URL       = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{year}"
ESPN_TEAM_STATS_URL   = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/seasons/{year}/types/2/teams/{espn_id}/statistics"
)
ESPN_PLAYER_STATS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/seasons/{season}/types/2/athletes/{espn_id}/statistics/0"
)
# Games — bulk event list (returns $ref items) then summary per event
ESPN_EVENTS_URL  = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/seasons/{year}/types/{stype}/events?limit=300"
)
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"
# Coaches — per team, season-specific
ESPN_COACHES_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/seasons/2025/teams/{espn_id}/coaches?limit=20"
)

STAT_POSITIONS = {
    "QB", "RB", "FB", "WR", "TE", "K", "P",
    "DE", "DT", "NT", "LB", "OLB", "ILB", "MLB",
    "CB", "S", "SS", "FS", "DB",
}

TEAM_INFO = {
    "ARI": ("NFC", "West"),   "ATL": ("NFC", "South"),
    "BAL": ("AFC", "North"),  "BUF": ("AFC", "East"),
    "CAR": ("NFC", "South"),  "CHI": ("NFC", "North"),
    "CIN": ("AFC", "North"),  "CLE": ("AFC", "North"),
    "DAL": ("NFC", "East"),   "DEN": ("AFC", "West"),
    "DET": ("NFC", "North"),  "GB":  ("NFC", "North"),
    "HOU": ("AFC", "South"),  "IND": ("AFC", "South"),
    "JAX": ("AFC", "South"),  "KC":  ("AFC", "West"),
    "LV":  ("AFC", "West"),   "LAC": ("AFC", "West"),
    "LAR": ("NFC", "West"),   "MIA": ("AFC", "East"),
    "MIN": ("NFC", "North"),  "NE":  ("AFC", "East"),
    "NO":  ("NFC", "South"),  "NYG": ("NFC", "East"),
    "NYJ": ("AFC", "East"),   "PHI": ("NFC", "East"),
    "PIT": ("AFC", "North"),  "SF":  ("NFC", "West"),
    "SEA": ("NFC", "West"),   "TB":  ("NFC", "South"),
    "TEN": ("AFC", "South"),  "WSH": ("NFC", "East"),
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def get_json(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt)


def build_espn_to_db_map():
    """Build {espn_id_str: db_team_id} from existing teams."""
    teams = Team.query.filter(Team.api_id.like("espn_%")).all()
    return {t.api_id.replace("espn_", ""): t.id for t in teams}


# ══════════════════════════════════════════════════════════════════════════════
# 1. ROSTERS — teams + players (2025 current)
# ══════════════════════════════════════════════════════════════════════════════
def seed_rosters():
    print("\n=== [1/7] Refreshing Rosters ===")
    data = get_json(ESPN_TEAMS_URL)
    if not data:
        print("  FAILED to fetch teams list"); return {}

    entries = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
    team_map = {}
    t_ins = t_upd = 0

    for entry in entries:
        t = entry.get("team", {})
        espn_id = str(t.get("id", ""))
        abbr = t.get("abbreviation", "")
        conf, div = TEAM_INFO.get(abbr, ("", ""))
        color     = t.get("color", "")
        alt_color = t.get("alternateColor", "")

        existing = Team.query.filter_by(api_id=f"espn_{espn_id}").first()
        if existing:
            existing.name           = t.get("shortDisplayName", existing.name)
            existing.abbreviation   = abbr
            existing.city           = t.get("location", existing.city)
            existing.full_name      = t.get("displayName", existing.full_name)
            existing.conference     = conf
            existing.division       = div
            if color:     existing.primary_color   = f"#{color}"
            if alt_color: existing.secondary_color = f"#{alt_color}"
            team_map[espn_id] = existing.id
            t_upd += 1
        else:
            team = Team(
                name=t.get("shortDisplayName", ""),
                abbreviation=abbr,
                city=t.get("location", ""),
                full_name=t.get("displayName", ""),
                conference=conf, division=div,
                primary_color=f"#{color}" if color else None,
                secondary_color=f"#{alt_color}" if alt_color else None,
                api_id=f"espn_{espn_id}",
            )
            db.session.add(team)
            db.session.flush()
            team_map[espn_id] = team.id
            t_ins += 1

    db.session.commit()
    print(f"  Teams: {t_ins} inserted, {t_upd} updated")

    p_ins = p_upd = 0
    for entry in entries:
        t = entry.get("team", {})
        espn_id   = str(t.get("id", ""))
        abbr      = t.get("abbreviation", "")
        team_db_id = team_map.get(espn_id)

        print(f"  Roster {abbr}...", end=" ", flush=True)
        roster = get_json(ESPN_ROSTER_URL.format(espn_id=espn_id))
        if not roster:
            print("FAILED"); continue

        ins = upd = 0
        for group in roster.get("athletes", []):
            for a in group.get("items", []):
                pid    = str(a.get("id", ""))
                api_id = f"espn_{pid}"

                status_obj = a.get("status", "Active")
                if isinstance(status_obj, dict):
                    status = (
                        status_obj.get("type", {}).get("description", "Active")
                        if isinstance(status_obj.get("type"), dict)
                        else status_obj.get("name", "Active")
                    )
                else:
                    status = str(status_obj) if status_obj else "Active"

                dw = a.get("displayWeight", "")
                weight = None
                if dw:
                    try: weight = int(dw.replace(" lbs", "").strip())
                    except: pass

                jersey_num = None
                if a.get("jersey"):
                    try: jersey_num = int(a["jersey"])
                    except: pass

                exp     = a.get("experience", {}).get("years") if isinstance(a.get("experience"), dict) else None
                college = a.get("college", {}).get("name", "")  if isinstance(a.get("college"), dict)   else ""
                headshot= a.get("headshot", {}).get("href", "") if isinstance(a.get("headshot"), dict)   else ""

                existing = Player.query.filter_by(api_id=api_id).first()
                if existing:
                    existing.team_id      = team_db_id
                    existing.name         = a.get("fullName", existing.name)
                    existing.first_name   = a.get("firstName", existing.first_name)
                    existing.last_name    = a.get("lastName", existing.last_name)
                    existing.position     = a.get("position", {}).get("abbreviation", existing.position)
                    existing.jersey_number= jersey_num
                    existing.status       = status
                    existing.height       = a.get("displayHeight", existing.height)
                    existing.weight       = weight
                    existing.age          = a.get("age", existing.age)
                    existing.experience   = exp
                    existing.college      = college
                    existing.image_url    = headshot or existing.image_url
                    upd += 1
                else:
                    db.session.add(Player(
                        team_id=team_db_id,
                        name=a.get("fullName", ""),
                        first_name=a.get("firstName", ""),
                        last_name=a.get("lastName", ""),
                        position=a.get("position", {}).get("abbreviation", ""),
                        jersey_number=jersey_num,
                        status=status,
                        height=a.get("displayHeight", ""),
                        weight=weight,
                        age=a.get("age"),
                        experience=exp,
                        college=college,
                        image_url=headshot or None,
                        api_id=api_id,
                    ))
                    ins += 1

        db.session.commit()
        p_ins += ins; p_upd += upd
        print(f"{ins} new, {upd} updated")
        time.sleep(0.3)

    print(f"  Players total: {p_ins} inserted, {p_upd} updated")
    return team_map


# ══════════════════════════════════════════════════════════════════════════════
# 2. COACHES — ESPN core per-team coaches endpoint (2025 season)
# ══════════════════════════════════════════════════════════════════════════════
def seed_venues_and_coaches(espn_to_db):
    print("\n=== [2/7] Coaches ===")
    c_ins = c_upd = 0

    for espn_id, team_db_id in espn_to_db.items():
        url  = ESPN_COACHES_URL.format(espn_id=espn_id)
        data = get_json(url)
        if not data:
            time.sleep(0.1); continue

        for item in data.get("items", []):
            # Each item is a $ref URL string — follow it
            ref_url = item if isinstance(item, str) else item.get("$ref", "")
            if not ref_url:
                continue
            coach_data = get_json(ref_url)
            if not coach_data:
                continue

            coach_espn = str(coach_data.get("id", ""))
            if not coach_espn:
                continue
            c_api_id = f"espn_{coach_espn}"
            fname = coach_data.get("firstName", "")
            lname = coach_data.get("lastName", "")
            name  = f"{fname} {lname}".strip()
            if not name:
                continue

            existing_c = Coach.query.filter_by(api_id=c_api_id).first()
            if existing_c:
                existing_c.name    = name
                existing_c.team_id = team_db_id
                c_upd += 1
            else:
                db.session.add(Coach(
                    team_id=team_db_id,
                    name=name,
                    title="Head Coach",
                    api_id=c_api_id,
                ))
                c_ins += 1

            time.sleep(0.05)

        db.session.commit()
        time.sleep(0.1)

    print(f"  Coaches: {c_ins} inserted, {c_upd} updated")
    print(f"  (Venues seeded inline during game seeding)")


# ══════════════════════════════════════════════════════════════════════════════
# 3. SEASONS — 2022-2025
# ══════════════════════════════════════════════════════════════════════════════
def seed_seasons(years):
    print(f"\n=== [3/7] Seasons {years} ===")
    season_id_map = {}  # (year, type_num) -> db season id

    TYPE_NAMES = {1: "Preseason", 2: "Regular", 3: "Postseason"}

    for year in years:
        for type_num, sname in TYPE_NAMES.items():
            api_id   = f"espn_{year}_{type_num}"
            existing = Season.query.filter_by(api_id=api_id).first()
            if existing:
                season_id_map[(year, type_num)] = existing.id
            else:
                s = Season(
                    year=year,
                    season_type=sname,
                    name=f"{year} NFL {sname} Season",
                    api_id=api_id,
                )
                db.session.add(s)
                db.session.flush()
                season_id_map[(year, type_num)] = s.id
                print(f"  Created: {year} {sname}")

    db.session.commit()
    print(f"  Season records ready: {len(season_id_map)}")
    return season_id_map


# ══════════════════════════════════════════════════════════════════════════════
# 4. GAMES + VENUES — bulk events list → summary per event
# ══════════════════════════════════════════════════════════════════════════════
def _upsert_venue(v_data):
    """Seed venue from gameInfo.venue dict. Returns venue api_id or None."""
    vid = str(v_data.get("id", ""))
    if not vid:
        return None
    v_api_id = f"espn_{vid}"
    addr     = v_data.get("address", {})
    grass    = v_data.get("grass")
    surface  = "Grass" if grass is True else ("Turf" if grass is False else None)

    existing = Venue.query.filter_by(api_id=v_api_id).first()
    if not existing:
        db.session.add(Venue(
            name=v_data.get("fullName", "Unknown"),
            city=addr.get("city"),
            state=addr.get("state"),
            country=addr.get("country", "USA"),
            surface=surface,
            api_id=v_api_id,
        ))
    return v_api_id


def seed_games(years, espn_to_db, season_id_map):
    print(f"\n=== [4/7] Games + Venues {years} ===")
    g_ins = g_upd = v_ins_total = 0

    schedule_plan = [
        (2, "Regular"),
        (3, "Postseason"),
    ]

    for year in years:
        for stype_num, stype_label in schedule_plan:
            season_db_id = season_id_map.get((year, stype_num))

            # 1. Get all event IDs for this season/type
            url  = ESPN_EVENTS_URL.format(year=year, stype=stype_num)
            data = get_json(url)
            if not data:
                print(f"  {year} {stype_label}: could not fetch event list"); continue

            items = data.get("items", [])
            if not items:
                print(f"  {year} {stype_label}: 0 events"); continue

            # Extract event IDs from $ref URLs
            event_ids = []
            for item in items:
                ref = item if isinstance(item, str) else item.get("$ref", "")
                # URL pattern: .../events/401671789?...
                try:
                    eid = ref.split("/events/")[1].split("?")[0]
                    event_ids.append(eid)
                except (IndexError, AttributeError):
                    continue

            print(f"  {year} {stype_label}: {len(event_ids)} events — fetching summaries...")
            g_ins_t = g_upd_t = 0

            # 2. Fetch summary for each event
            for event_id in event_ids:
                api_id  = f"espn_{event_id}"
                sum_url = ESPN_SUMMARY_URL.format(event_id=event_id)
                sdata   = get_json(sum_url)
                if not sdata:
                    time.sleep(0.1); continue

                header = sdata.get("header", {})
                comps  = header.get("competitions", [])
                if not comps:
                    continue
                comp = comps[0]

                # Teams + scores
                home_espn = away_espn = None
                home_score = away_score = None
                for c in comp.get("competitors", []):
                    eid   = str(c.get("team", {}).get("id", ""))
                    raw_s = c.get("score")
                    score = None
                    if raw_s is not None:
                        try: score = int(float(str(raw_s)))
                        except: pass
                    if c.get("homeAway") == "home":
                        home_espn, home_score = eid, score
                    else:
                        away_espn, away_score = eid, score

                home_db_id = espn_to_db.get(home_espn)
                away_db_id = espn_to_db.get(away_espn)
                status     = comp.get("status", {}).get("type", {}).get("description", "Scheduled")
                week       = header.get("week")

                # Date
                game_date = None
                date_str  = comp.get("date", "")
                if date_str:
                    try:
                        game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    except: pass

                # Broadcast
                broadcast = None
                for b in comp.get("broadcasts", []):
                    media = b.get("media", {}).get("shortName", "")
                    if media:
                        broadcast = media; break

                # Game info (venue + attendance)
                gi         = sdata.get("gameInfo", {})
                attendance = gi.get("attendance")
                v_data     = gi.get("venue", {})
                _upsert_venue(v_data)

                existing = Game.query.filter_by(api_id=api_id).first()
                if existing:
                    existing.home_score = home_score
                    existing.away_score = away_score
                    existing.status     = status
                    existing.broadcast  = broadcast
                    if attendance is not None: existing.attendance = attendance
                    g_upd_t += 1
                else:
                    db.session.add(Game(
                        season_id=season_db_id,
                        home_team_id=home_db_id,
                        away_team_id=away_db_id,
                        week=week,
                        season_year=year,
                        season_type=stype_label,
                        game_date=game_date,
                        home_score=home_score,
                        away_score=away_score,
                        status=status,
                        neutral_site=comp.get("neutralSite", False),
                        broadcast=broadcast,
                        attendance=attendance,
                        api_id=api_id,
                    ))
                    g_ins_t += 1

                time.sleep(0.15)

            db.session.commit()
            g_ins += g_ins_t; g_upd += g_upd_t
            print(f"  {year} {stype_label}: {g_ins_t} new, {g_upd_t} updated")

    db.session.commit()
    v_count = Venue.query.count()
    print(f"  Games total: {g_ins} inserted, {g_upd} updated")
    print(f"  Venues in DB: {v_count}")


# ══════════════════════════════════════════════════════════════════════════════
# 5. TEAM STATS — season totals for each year
# ══════════════════════════════════════════════════════════════════════════════
def seed_team_stats(years, espn_to_db):
    print(f"\n=== [5/7] Team Stats {years} ===")
    total_ins = total_upd = 0

    for year in years:
        ins = upd = 0
        for espn_id, team_db_id in espn_to_db.items():
            url  = ESPN_TEAM_STATS_URL.format(year=year, espn_id=espn_id)
            data = get_json(url)
            if not data:
                time.sleep(0.05); continue

            for cat in data.get("splits", {}).get("categories", []):
                cat_name = cat.get("name", "general").lower()
                for stat in cat.get("stats", []):
                    stat_name = stat.get("abbreviation") or stat.get("name", "")
                    raw_val   = stat.get("value")
                    if not stat_name or raw_val is None:
                        continue
                    try:
                        val = float(raw_val)
                        if val == 0.0:
                            continue
                        existing = TeamStat.query.filter_by(
                            team_id=team_db_id,
                            game_id=None,
                            stat_category=cat_name,
                            stat_type=stat_name,
                            season_year=year,
                        ).first()
                        if existing:
                            existing.value = val
                            upd += 1
                        else:
                            db.session.add(TeamStat(
                                team_id=team_db_id,
                                game_id=None,
                                season_year=year,
                                week=None,
                                stat_category=cat_name,
                                stat_type=stat_name,
                                value=val,
                            ))
                            ins += 1
                    except (ValueError, TypeError):
                        continue

            db.session.commit()
            time.sleep(0.1)

        total_ins += ins; total_upd += upd
        print(f"  {year} team stats: {ins} inserted, {upd} updated")

    print(f"  Team stats total: {total_ins} inserted, {total_upd} updated")


# ══════════════════════════════════════════════════════════════════════════════
# 6. INJURIES — derived from player roster status
# ══════════════════════════════════════════════════════════════════════════════
def seed_injuries():
    print("\n=== [6/7] Injuries ===")
    CURRENT_YEAR = 2025
    STATUS_MAP = {
        "Injured Reserve": "IR",
        "IR":              "IR",
        "Out":             "Out",
        "Doubtful":        "Doubtful",
        "Questionable":    "Questionable",
        "Practice Squad":  "Practice Squad",
        "PUP":             "PUP",
        "NFI":             "NFI",
    }

    injured = Player.query.filter(
        Player.status.notin_(["Active", "Free Agent"]),
        Player.status.isnot(None),
        Player.team_id.isnot(None),
    ).all()

    ins = upd = 0
    for player in injured:
        raw    = (player.status or "").strip()
        status = STATUS_MAP.get(raw, raw)

        existing = Injury.query.filter_by(
            player_id=player.id,
            season_year=CURRENT_YEAR,
            week=None,
        ).first()
        if existing:
            existing.status  = status
            existing.team_id = player.team_id
            upd += 1
        else:
            db.session.add(Injury(
                player_id=player.id,
                team_id=player.team_id,
                status=status,
                season_year=CURRENT_YEAR,
                week=None,
            ))
            ins += 1

    db.session.commit()
    print(f"  Injuries: {ins} inserted, {upd} updated  ({len(injured)} non-Active players)")


# ══════════════════════════════════════════════════════════════════════════════
# (player stats for 2024+2025 are handled by seed_stats_2024.py / seed_stats_2025.py)
# kept here for reference if individual years need to be re-seeded
# ══════════════════════════════════════════════════════════════════════════════
def seed_player_stats(year):
    print(f"\n=== [7/7] Player Stats {year} ===")
    players = Player.query.filter(
        Player.api_id.like("espn_%"),
        Player.position.in_(STAT_POSITIONS),
    ).all()

    print(f"  Processing {len(players)} players...")
    total_ins = total_upd = skipped = 0
    batch_size = 50

    for i, player in enumerate(players, 1):
        espn_id = player.api_id.replace("espn_", "")
        url     = ESPN_PLAYER_STATS_URL.format(season=year, espn_id=espn_id)
        data    = get_json(url)

        if not data:
            skipped += 1
            if i % 200 == 0:
                print(f"  [{i}/{len(players)}] skipped: {skipped}")
            time.sleep(0.05)
            continue

        ins = upd = 0
        for cat in data.get("splits", {}).get("categories", []):
            cat_name = cat.get("name", "general").lower()
            for stat in cat.get("stats", []):
                stat_name = stat.get("abbreviation") or stat.get("name", "")
                raw_val   = stat.get("value")
                if not stat_name or raw_val is None:
                    continue
                try:
                    val = float(raw_val)
                    if val == 0.0:
                        continue
                    existing = PlayerStat.query.filter_by(
                        player_id=player.id,
                        game_id=None,
                        stat_category=cat_name,
                        stat_type=stat_name,
                        season_year=year,
                    ).first()
                    if existing:
                        existing.value = val
                        upd += 1
                    else:
                        db.session.add(PlayerStat(
                            player_id=player.id,
                            game_id=None,
                            season_year=year,
                            week=None,
                            stat_category=cat_name,
                            stat_type=stat_name,
                            value=val,
                        ))
                        ins += 1
                except (ValueError, TypeError):
                    continue

        total_ins += ins; total_upd += upd
        if ins > 0 or upd > 0:
            print(f"  {player.name} ({player.position}): {ins} new, {upd} updated")

        if i % batch_size == 0:
            db.session.commit()
            print(f"  --- batch [{i}/{len(players)}] committed ---")

        time.sleep(0.1)

    db.session.commit()
    print(f"  {year} done: {total_ins} inserted, {total_upd} updated, {skipped} skipped")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    start = datetime.now()
    print("=" * 60)
    print("NFL PARLAY TRACKER — Full Data Seed")
    print("=" * 60)

    with app.app_context():
        # 1. Rosters (teams + players, 2025 current)
        team_map = seed_rosters()
        if not team_map:
            print("Could not build team map — aborting."); exit(1)

        # 2. Venues + coaches
        seed_venues_and_coaches(team_map)

        # 3. Seasons (2024-2025 only)
        season_id_map = seed_seasons(years=[2024, 2025])

        # 4. Games — 2024 + 2025 (regular + postseason)
        seed_games(
            years=[2024, 2025],
            espn_to_db=team_map,
            season_id_map=season_id_map,
        )

        # 5. Team stats — 2024 + 2025
        seed_team_stats(years=[2024, 2025], espn_to_db=team_map)

        # 6. Injuries (current roster status)
        seed_injuries()

        elapsed = (datetime.now() - start).seconds // 60
        print("\n" + "=" * 60)
        print(f"ALL DONE — elapsed ~{elapsed} min")
        print("=" * 60)
