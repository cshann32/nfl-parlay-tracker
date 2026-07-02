# Beast Mode NFL Parlay Tracker

A full-stack NFL analytics and parlay tracking web app — Seattle Seahawks themed. Track your bets, monitor live odds, analyze player and team stats, and let the app auto-settle your parlay legs after games. All data lives in your own PostgreSQL database.

---

## Features

### Parlay Tracking
- Log parlays with individual legs, odds, stake, and sportsbook
- Win/loss/push tracking with automatic P&L and ROI calculation
- **Auto-settle** — completed game results automatically resolve pending legs (spread, moneyline, total)
- Analytics: monthly P&L, win rate by week, ROI by sportsbook and leg count

### Live Odds (The Odds API)
- Sync live NFL spread, moneyline, and O/U lines from 8+ bookmakers
- Lines auto-populate the parlay form when you select a game
- 4-hour cooldown enforced to protect the free-plan 500-credit quota
- Free plan: 3 credits per sync

### NFL Data
- **ESPN (free, no key required)** — teams, rosters, schedule, scores, news, game stats
- **RapidAPI (optional)** — extended data: plays, boxscores, draft, historical stats
- Sunday 11 PM ET auto-sync: scores → stats → rosters → odds → auto-settle

### Dashboard
- Seahawks KPIs, recent results, W-L record, win probability gauges
- 12s Corner — Seahawks-only news section, shown first on the news page
- NFL Headlines strip
- Offseason countdown to kickoff night

### Reports & Charts
- Passing / Rushing / Receiving stat leaders
- NFL Standings with division breakdowns
- Team Performance deep-dives (weekly scoring, full game log)
- Score & Totals Distribution (O/U research)
- Head-to-Head matchup explorer
- Player Research (week-by-week game log for prop bets)
- Prop Analyzer and AI-powered predictions

### Admin Panel
- **API Tester** — test NFL API and Odds API connections, try new keys before saving, replace keys live
- **The Commissioner** — automated DB integrity tool: auto-fixes orphans, duplicates, stuck legs, season type labels, and parlay mismatches; flags issues that need human attention
- **Settings** — configure every app setting from the browser: API keys, season year, log level, scheduler, upload limits, Commissioner thresholds
- **Sync Manager** — run ESPN and RapidAPI syncs on demand per category
- **DB Health** — table sizes, row counts, raw SQL runner
- **Scheduler** — toggle auto-sync and weekly stats job on/off

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, Flask 3, Flask-Login, Flask-Migrate, Flask-WTF |
| Database | PostgreSQL 15 + SQLAlchemy 2 |
| Sessions / Cache | Redis 7 + Flask-Session |
| Scheduling | APScheduler (background + cron jobs) |
| Charts | Chart.js 4 |
| UI | Bootstrap 5.3, Bootstrap Icons, Bebas Neue + Barlow Condensed |
| Proxy / SSL | Nginx (self-signed cert for LAN HTTPS) |
| Deployment | Docker Compose + Gunicorn (gthread workers) |

---

## Quick Start — Docker Hub (no source code needed)

You can pull and run the app from Docker Hub on any machine with Docker.

### What you need (3 files)

```
docker/compose.hub.yml   ← orchestrates all 4 containers
docker/nginx.conf        ← Nginx reverse proxy config
.env                     ← your API keys and secret
```

### 1. Get the files

```bash
mkdir nfl-parlay-tracker && cd nfl-parlay-tracker
mkdir docker logs uploads

# Download compose file
curl -O https://raw.githubusercontent.com/cshann32/nfl-parlay-tracker/main/docker/compose.hub.yml -o docker/compose.hub.yml
curl -O https://raw.githubusercontent.com/cshann32/nfl-parlay-tracker/main/docker/nginx.conf -o docker/nginx.conf
curl -O https://raw.githubusercontent.com/cshann32/nfl-parlay-tracker/main/.env.example -o .env
```

Or just clone the repo and skip the build:

```bash
git clone https://github.com/cshann32/nfl-parlay-tracker.git
cd nfl-parlay-tracker
cp .env.example .env
```

### 2. Configure `.env`

At minimum set:
```env
SECRET_KEY=<any long random string>
THE_ODDS_API_KEY=<your the-odds-api.com key>   # free plan works
NFL_API_KEY=<your RapidAPI key>                # optional
```

Everything else (DATABASE_URL, REDIS_URL) is pre-wired for Docker.

### 3. Run

```bash
docker-compose -f docker/compose.hub.yml up -d
```

App is live at **http://localhost:8080**

### 4. First-time setup

```bash
# Create admin user
docker exec -it nfl-parlay-tracker-app-1 flask seed-admin

# Seed default settings
docker exec -it nfl-parlay-tracker-app-1 flask create-settings
```

Then log in and go to **Admin → Sync** and run in order:
1. `espn_teams` — all 32 teams
2. `espn_roster` — current rosters
3. `espn_schedule` — full schedule (2024, 2025, 2026)
4. `the_odds_api` — live lines (costs 3 credits)
5. `game_stats` — per-game player stats

All ESPN syncs are **free**. The Odds API sync costs 3 credits per run (500/month free).

---

## Quick Start — Build from Source

```bash
git clone https://github.com/cshann32/nfl-parlay-tracker.git
cd nfl-parlay-tracker
cp .env.example .env          # configure your keys
docker-compose up --build -d  # builds image + starts all 4 containers
```

App is live at **http://localhost:8081** (or **https://localhost:8443** if SSL is configured)

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✓ | Flask session secret — set to any long random string |
| `THE_ODDS_API_KEY` | Recommended | the-odds-api.com key for live odds (free: 500 credits/month) |
| `NFL_API_KEY` | Optional | RapidAPI key for extended stats (plays, boxscores, draft) |
| `DATABASE_URL` | Auto | Pre-set for Docker — `postgresql://nfl:nflpassword@db:5432/nfl_tracker` |
| `REDIS_URL` | Auto | Pre-set for Docker — `redis://redis:6379/0` |
| `SESSION_COOKIE_SECURE` | Auto | Set `false` for plain HTTP, `true` for HTTPS |
| `LOG_LEVEL` | Optional | `DEBUG` / `INFO` / `WARNING` (default: `INFO`) |

All settings can also be changed at runtime from **Admin → Settings** — no restart required.

---

## What's in the Image vs. What Isn't

**Included in the Docker image:**
- All application code, templates, and static assets
- Python dependencies
- Database migrations

**NOT included (you provide these):**
- The database data — starts empty, populate via Admin → Sync
- Your `.env` file (API keys, secret key)
- SSL certificates (auto-generated if you run the setup script)
- Uploaded documents

The database volume persists across container restarts. To fully reset: `docker-compose down -v`

---

## CLI Commands

```bash
flask seed-admin          # create initial admin user
flask create-settings     # seed default app settings
flask commissioner        # run full DB integrity audit + auto-fix
flask db upgrade          # apply database migrations
flask sync-nfl -c teams   # sync a specific category
```

---

## Project Structure

```
app/
├── blueprints/
│   ├── admin/        # Admin panel: sync, settings, commissioner, api-tester
│   ├── api/          # JSON endpoints for all charts and AJAX
│   ├── auth/         # Login, register, profile
│   ├── dashboard/    # Main dashboard + news
│   ├── parlays/      # Parlay CRUD, auto-settle
│   ├── reports/      # Stat leaders, standings, matchups, player research
│   └── stats/        # Players, teams, prop analyzer, predictions
├── models/           # SQLAlchemy models
├── services/
│   ├── sync/         # ESPN + RapidAPI + The Odds API sync modules
│   ├── commissioner.py   # DB integrity and auto-fix engine
│   ├── parlay_service.py # Parlay CRUD + auto-settle logic
│   └── the_odds_api.py   # Odds API client + game matching
├── templates/        # Jinja2 HTML templates (Seahawks Beast Mode theme)
└── static/           # CSS, JS, team logos, images
docker/
├── compose.hub.yml   # Pull-and-run compose (no source needed)
├── nginx.conf        # Nginx reverse proxy + SSL
└── ssl/              # Self-signed certificates (LAN HTTPS)
migrations/           # Alembic database migrations
```
