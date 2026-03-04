# Beast Mode NFL Parlay Tracker

A full-stack NFL analytics and parlay tracking web app built with Flask and PostgreSQL. Track your bets, analyze player and team data synced directly from ESPN, and explore live charts — all from your own database.

---

## Features

### Parlay Tracking
- Log parlays with individual legs, odds, stake, and sportsbook
- Win/loss/push tracking with automatic P&L calculation
- Analytics dashboard: monthly P&L, ROI, win rate by sportsbook, leg count breakdown

### NFL Data (ESPN-powered, free API)
- **Teams** — all 32 NFL teams with logos, colors, conference/division
- **Rosters** — full player roster with photos, positions, jersey numbers, and injury status
- **Schedule & Scores** — game results, scores, and week-by-week schedule
- **News** — latest NFL headlines with images
- **Odds** — game odds synced from ESPN

### Reports & Charts
Live dashboard charts built entirely from your local database:
- Passing / Rushing / Receiving stat leaders
- NFL Standings (W-L-T, PF, PA, home/away splits by division)
- Team Performance deep-dive (weekly scoring chart, full game log)
- Score & Totals Distribution (histogram + weekly trend — built for O/U research)
- Head-to-Head matchup explorer
- Player Research (week-by-week game log for prop betting)
- ROI by parlay leg count

### Players Page
- Grouped by position (QB, RB, WR, TE, OL, DL, LB, DB, K/P)
- Live search — filter by name or team abbreviation instantly
- Position tab filters with per-group player counts

### Admin Panel
- Sync manager — run ESPN syncs on demand (teams, roster, schedule, news, odds)
- DB Health monitor with table row counts
- DB Audit tool — detects duplicate teams, players, games, odds, and news with one-click cleanup

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, Flask 3, Flask-Login, Flask-Migrate |
| Database | PostgreSQL + SQLAlchemy 2 |
| Scheduling | APScheduler |
| Sessions | Redis + Flask-Session |
| Charts | Chart.js |
| UI | Bootstrap 5, Bootstrap Icons |
| Deployment | Docker + Gunicorn + Nginx |

---

## Quick Start

### 1. Clone & configure

```bash
git clone https://github.com/cshann32/nfl-parlay-tracker.git
cd nfl-parlay-tracker
cp .env.example .env
```

Open `.env` and set at minimum:
```
SECRET_KEY=<any long random string>
NFL_API_KEY=<your RapidAPI key — optional, ESPN syncs work without it>
```
Everything else (database URL, Redis URL) is pre-configured to work with Docker out of the box.

---

### 2. Run with Docker (recommended)

#### Production mode — Gunicorn + Nginx on port 80

```bash
docker-compose up --build -d
```

The app is available at **http://localhost**

#### Development mode — Flask hot-reload on port 5000

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The app is available at **http://localhost:5000** — file edits reflect immediately without rebuilding.

#### Useful commands

```bash
# View logs
docker-compose logs -f app

# Stop everything
docker-compose down

# Stop and wipe the database volume (full reset)
docker-compose down -v

# Open a shell inside the app container
docker-compose exec app sh

# Run a Flask CLI command
docker-compose exec app flask db upgrade
```

---

### 3. Run locally (without Docker)

```bash
# Requires: PostgreSQL + Redis running locally
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

flask db upgrade          # run migrations
python run.py             # dev server → http://localhost:5000
```

---

### 4. Populate data

Log in, then go to **Admin → Sync** and run these in order:
1. `espn_teams` — all 32 NFL teams with logos and colors
2. `espn_roster` — full rosters with player photos and positions
3. `espn_schedule` — game schedule and final scores
4. `espn_news` — latest NFL headlines
5. `espn_odds` — current game odds

All ESPN syncs are **free** — no API key required.

---

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | Flask session secret |
| `REDIS_URL` | Redis connection string |
| `RAPIDAPI_KEY` | Optional — RapidAPI key for extended NFL data |

---

## Project Structure

```
app/
├── blueprints/
│   ├── admin/        # Admin panel, sync management, DB audit
│   ├── api/          # JSON API endpoints for all charts
│   ├── auth/         # Login, register, profile
│   ├── dashboard/    # Main dashboard + news feed
│   ├── parlays/      # Parlay CRUD and analytics
│   ├── reports/      # Report pages (standings, team perf, etc.)
│   └── stats/        # Players, teams, leaders, prop analyzer
├── models/           # SQLAlchemy models
├── services/
│   ├── sync/         # ESPN sync modules
│   └── stats_service.py, parlay_service.py, ...
├── templates/        # Jinja2 HTML templates
└── static/           # CSS, JS, images
migrations/           # Alembic DB migrations
scripts/              # Data seeding scripts
```
