"""
Seed advanced stats from nfl-data-py (nflverse open data).

Adds per-player season stats:
  ngs_passing  — CPOE, air yards, time-to-throw, aggressiveness
  ngs_rushing  — rush efficiency, yards over expected, time-to-LOS
  ngs_receiving — separation, cushion, YAC above expectation
  adv_passing  — EPA, air yards, YAC, PACR, DAKOTA
  adv_rushing  — EPA
  adv_receiving — EPA, air yards, YAC, RACR, target share, WOPR, fantasy pts

Run: .venv/bin/python3 seed_advanced_stats.py
"""
import warnings
warnings.filterwarnings("ignore")

import re
import unicodedata
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import nfl_data_py as nfl

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.stat import PlayerStat

app = create_app()

# nfl-data-py team abbr divergences from our DB
TEAM_FIX = {"WAS": "WSH"}

# ──────────────────────────────────────────
# Stat field maps: (nflverse_col, our_abbr)
# ──────────────────────────────────────────
NGS_PASSING = [
    ("avg_time_to_throw",                    "ATT2TH"),
    ("avg_intended_air_yards",               "AVG_IAY"),
    ("avg_completed_air_yards",              "AVG_CAY"),
    ("aggressiveness",                       "AGG"),
    ("completion_percentage_above_expectation", "CPOE"),
    ("avg_air_yards_to_sticks",              "AVG_AYTS"),
    ("avg_air_yards_differential",           "AVG_AYD"),
]

NGS_RUSHING = [
    ("efficiency",                           "EFF"),
    ("percent_attempts_gte_eight_defenders", "PCT8DEF"),
    ("avg_time_to_los",                      "TT_LOS"),
    ("rush_yards_over_expected_per_att",     "RYOE_PA"),
    ("rush_pct_over_expected",               "RPOE"),
    ("expected_rush_yards",                  "EXP_RY"),
]

NGS_RECEIVING = [
    ("avg_cushion",                          "CUSHION"),
    ("avg_separation",                       "SEP"),
    ("avg_intended_air_yards",               "AVG_IAY"),
    ("percent_share_of_intended_air_yards",  "IAY_SH"),
    ("avg_yac",                              "AVG_YAC"),
    ("avg_yac_above_expectation",            "YAC_AE"),
]

# These come from import_weekly_data, aggregated to season
ADV_PASSING = [
    ("passing_epa",              "PASS_EPA",  "sum"),
    ("passing_air_yards",        "PASS_AY",   "sum"),
    ("passing_yards_after_catch","PASS_YAC",  "sum"),
    ("pacr",                     "PACR",      "mean"),
    ("dakota",                   "DAKOTA",    "mean"),
]

ADV_RUSHING = [
    ("rushing_epa",              "RUSH_EPA",  "sum"),
]

ADV_RECEIVING = [
    ("receiving_epa",              "REC_EPA",  "sum"),
    ("receiving_air_yards",        "REC_AY",   "sum"),
    ("receiving_yards_after_catch","REC_YAC",  "sum"),
    ("racr",                       "RACR",     "mean"),
    ("target_share",               "TGT_SH",  "mean"),
    ("air_yards_share",            "AY_SH",   "mean"),
    ("wopr_x",                     "WOPR",    "mean"),
    ("fantasy_points",             "FPTS",    "sum"),
    ("fantasy_points_ppr",         "FPTS_PPR","sum"),
]


# ──────────────────────────────────────────
# Player lookup helpers
# ──────────────────────────────────────────

def _norm(name):
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    name = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", name, flags=re.I)
    name = re.sub(r"[^\w\s]", "", name)
    return " ".join(name.lower().split())


def build_lookup():
    players = Player.query.join(Player.team).all()
    by_nt = {}   # (norm_name, team_abbr) → player_id
    by_n  = {}   # norm_name → [player_id, ...]
    for p in players:
        abbr = p.team.abbreviation if p.team else None
        nn = _norm(p.name)
        if nn and abbr:
            by_nt[(nn, abbr)] = p.id
        if nn:
            by_n.setdefault(nn, []).append(p.id)
    return by_nt, by_n


def find_pid(display_name, team_abbr, by_nt, by_n):
    abbr = TEAM_FIX.get(team_abbr, team_abbr)
    nn   = _norm(display_name)
    pid  = by_nt.get((nn, abbr))
    if pid:
        return pid
    matches = by_n.get(nn, [])
    return matches[0] if len(matches) == 1 else None


# ──────────────────────────────────────────
# Upsert helper
# ──────────────────────────────────────────

def upsert(player_id, season_year, category, stat_type, value):
    if value is None or (isinstance(value, float) and (pd.isna(value) or value == 0.0)):
        return
    existing = PlayerStat.query.filter_by(
        player_id=player_id,
        game_id=None,
        season_year=season_year,
        stat_category=category,
        stat_type=stat_type,
    ).first()
    if existing:
        existing.value = round(float(value), 4)
    else:
        db.session.add(PlayerStat(
            player_id=player_id,
            game_id=None,
            season_year=season_year,
            stat_category=category,
            stat_type=stat_type,
            value=round(float(value), 4),
        ))


# ──────────────────────────────────────────
# NGS seeder (week=0 → season totals)
# ──────────────────────────────────────────

def seed_ngs(year, by_nt, by_n):
    total = skipped = 0
    for stat_kind, fields, cat in [
        ("passing",   NGS_PASSING,   "ngs_passing"),
        ("rushing",   NGS_RUSHING,   "ngs_rushing"),
        ("receiving", NGS_RECEIVING, "ngs_receiving"),
    ]:
        try:
            df = nfl.import_ngs_data(stat_kind, [year])
        except Exception as e:
            print(f"  NGS {stat_kind} {year} error: {e}")
            continue
        if df is None or df.empty:
            continue
        df_s = df[df["week"] == 0]   # season totals
        for _, row in df_s.iterrows():
            pid = find_pid(row.get("player_display_name",""), row.get("team_abbr",""), by_nt, by_n)
            if not pid:
                skipped += 1
                continue
            for col, abbr in fields:
                if col in df_s.columns and pd.notna(row.get(col)):
                    upsert(pid, year, cat, abbr, row[col])
                    total += 1
    print(f"  NGS {year}: {total} stats written, {skipped} unmatched players")


# ──────────────────────────────────────────
# Advanced EPA/fantasy seeder (weekly → aggregated)
# ──────────────────────────────────────────

def seed_advanced(year, by_nt, by_n):
    try:
        w = nfl.import_weekly_data([year])
    except Exception as e:
        print(f"  Weekly data {year} error: {e}")
        return

    if w is None or w.empty:
        return

    # Regular season only
    if "season_type" in w.columns:
        w = w[w["season_type"] == "REG"]

    all_field_maps = [
        (ADV_PASSING,   "adv_passing"),
        (ADV_RUSHING,   "adv_rushing"),
        (ADV_RECEIVING, "adv_receiving"),
    ]

    # Collect per-player values
    buckets = {}   # pid → {(cat, abbr, agg_mode): [values]}

    for _, row in w.iterrows():
        name = row.get("player_display_name") or row.get("player_name") or ""
        team = row.get("recent_team", "")
        pid  = find_pid(name, team, by_nt, by_n)
        if not pid:
            continue
        if pid not in buckets:
            buckets[pid] = {}
        for fields, cat in all_field_maps:
            for col, abbr, mode in fields:
                if col not in w.columns:
                    continue
                v = row.get(col)
                if pd.isna(v):
                    continue
                key = (cat, abbr, mode)
                buckets[pid].setdefault(key, []).append(float(v))

    # Aggregate and upsert
    total = 0
    for pid, data in buckets.items():
        for (cat, abbr, mode), vals in data.items():
            if not vals:
                continue
            agg_val = sum(vals) if mode == "sum" else sum(vals) / len(vals)
            upsert(pid, year, cat, abbr, agg_val)
            total += 1

    print(f"  Advanced {year}: {total} stats written")


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

def seed():
    with app.app_context():
        by_nt, by_n = build_lookup()
        print(f"Player lookup: {len(by_nt)} name+team, {len(by_n)} name-only entries")

        for year in [2024, 2025]:
            print(f"\n--- {year} ---")
            seed_ngs(year, by_nt, by_n)
            seed_advanced(year, by_nt, by_n)
            db.session.commit()
            print(f"  Committed {year}")

        print("\nDone.")


if __name__ == "__main__":
    seed()
