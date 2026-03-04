"""
Entry point for the NFL Parlay Tracker Flask application.

CLI Commands:
  flask run               — Start development server
  flask db upgrade        — Apply database migrations
  flask seed-admin        — Create initial admin user
  flask sync-nfl          — Sync NFL data from API to local DB
  flask create-settings   — Seed default AppSettings
"""
import os
import sys
import click
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db

app = create_app()


# ---------------------------------------------------------------------------
# seed-admin
# ---------------------------------------------------------------------------
@app.cli.command('seed-admin')
@click.option('--username', default='admin', help='Admin username')
@click.option('--email', default='admin@nfltracker.local', help='Admin email')
@click.option('--password', prompt=True, hide_input=True,
              confirmation_prompt=True, help='Admin password')
def seed_admin(username, email, password):
    """Create the initial admin user (idempotent — skips if already exists)."""
    from app.models import User
    from app.models.user import UserRole

    with app.app_context():
        existing = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if existing:
            click.secho(f'Admin user "{existing.username}" already exists — skipping.', fg='yellow')
            return

        admin = User(
            username=username,
            email=email,
            role=UserRole.ADMIN,
            is_active=True,
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.secho(f'Admin user "{username}" created successfully.', fg='green')


# ---------------------------------------------------------------------------
# create-settings
# ---------------------------------------------------------------------------
@app.cli.command('create-settings')
def create_settings():
    """Seed default AppSetting rows (idempotent)."""
    from app.models import AppSetting

    defaults = [
        ('scheduler_enabled',   'false',  'Enable APScheduler background sync'),
        ('sync_interval_hours', '24',     'Hours between automatic syncs'),
        ('max_upload_size_mb',  '50',     'Maximum document upload size in MB'),
        ('current_season_year', '2024',   'NFL season year used for default queries'),
    ]

    with app.app_context():
        created = 0
        for key, value, desc in defaults:
            if not AppSetting.query.filter_by(key=key).first():
                db.session.add(AppSetting(key=key, value=value, description=desc))
                created += 1
        db.session.commit()
        click.secho(f'Created {created} setting(s).', fg='green')


# ---------------------------------------------------------------------------
# sync-nfl
# ---------------------------------------------------------------------------
VALID_CATEGORIES = [
    'all', 'seasons', 'teams', 'coaches', 'venues', 'players',
    'games', 'scoreboard', 'boxscore', 'plays', 'stats',
    'odds', 'news', 'draft',
]


@app.cli.command('sync-nfl')
@click.option(
    '--category', '-c',
    default='all',
    type=click.Choice(VALID_CATEGORIES, case_sensitive=False),
    show_default=True,
    help='Data category to sync.',
)
@click.option('--season', '-s', default=None, type=int,
              help='Season year to sync (e.g. 2024). Uses current if omitted.')
@click.option('--week', '-w', default=None, type=int,
              help='Week number to sync games/stats for.')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Stream log output to stdout.')
def sync_nfl(category, season, week, verbose):
    """Sync NFL data from the external API into the local database.

    Examples:\n
      flask sync-nfl                    # sync all categories\n
      flask sync-nfl -c teams           # teams only\n
      flask sync-nfl -c games -s 2024 -w 12  # week 12 games for 2024\n
    """
    import logging
    from app.services.sync import run_sync, run_full_sync

    if verbose:
        logging.getLogger('nfl').setLevel(logging.DEBUG)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        logging.getLogger('nfl').addHandler(handler)

    kwargs = {}
    if season:
        kwargs['season'] = season
    if week:
        kwargs['week'] = week

    with app.app_context():
        try:
            if category == 'all':
                click.echo('Starting full NFL data sync...')
                results = run_full_sync(app, triggered_by='cli', **kwargs)
                ok = sum(1 for r in results if r.get('status') == 'success')
                fail = len(results) - ok
                click.secho(
                    f'Full sync complete: {ok} succeeded, {fail} failed.',
                    fg='green' if fail == 0 else 'yellow',
                )
            else:
                click.echo(f'Syncing category: {category}...')
                result = run_sync(category, app, triggered_by='cli', **kwargs)
                inserted = result.get('records_inserted', 0)
                updated  = result.get('records_updated', 0)
                status   = result.get('status', 'unknown')
                color = 'green' if status == 'success' else 'red'
                click.secho(
                    f'[{status.upper()}] inserted={inserted} updated={updated}',
                    fg=color,
                )
        except Exception as exc:
            click.secho(f'Sync failed: {exc}', fg='red', err=True)
            sys.exit(1)


# ---------------------------------------------------------------------------
# db-health
# ---------------------------------------------------------------------------
@app.cli.command('db-health')
def db_health():
    """Print a quick database health summary."""
    from app.services.db_manager import get_db_stats

    with app.app_context():
        try:
            stats = get_db_stats()
            click.echo(f"DB version : {stats.get('pg_version', 'unknown')}")
            click.echo(f"DB size    : {stats.get('db_size', 'unknown')}")
            click.echo(f"Tables     : {stats.get('table_count', 'unknown')}")
            total_rows = stats.get('total_rows', {})
            if total_rows:
                click.echo('Row counts:')
                for tbl, cnt in sorted(total_rows.items()):
                    click.echo(f'  {tbl:<30} {cnt}')
        except Exception as exc:
            click.secho(f'DB health check failed: {exc}', fg='red', err=True)
            sys.exit(1)


# ---------------------------------------------------------------------------
# Shell context — `flask shell` has db + models pre-imported
# ---------------------------------------------------------------------------
@app.shell_context_processor
def make_shell_context():
    from app import models
    ctx = {'db': db, 'app': app}
    # Add every model class exported from app.models.__init__
    import inspect
    from sqlalchemy.orm import DeclarativeBase
    for name in dir(models):
        obj = getattr(models, name)
        if inspect.isclass(obj) and issubclass(obj, DeclarativeBase) and obj is not DeclarativeBase:
            ctx[name] = obj
    return ctx


if __name__ == '__main__':
    app.run(host='0.0.0.0')
