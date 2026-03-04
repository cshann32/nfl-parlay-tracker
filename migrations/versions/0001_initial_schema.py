"""Initial schema — all tables

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── Enum types via raw SQL (idempotent) ───────────────────────────────────
    # Using DO $$ EXCEPTION WHEN duplicate_object pattern is the most reliable
    # way to create PostgreSQL native enums in Alembic migrations.
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE userrole AS ENUM ('admin', 'user');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """))
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE syncstatus AS ENUM ('running', 'success', 'partial', 'failed');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """))
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE parlaystatustype AS ENUM ('pending', 'won', 'lost', 'push', 'partial');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """))
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE legtype AS ENUM ('spread', 'moneyline', 'total', 'player_prop', 'team_prop', 'parlay');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """))
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE legresult AS ENUM ('pending', 'won', 'lost', 'push');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """))
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE parsestatus AS ENUM ('pending', 'success', 'partial', 'failed');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """))

    # Helper: reference an already-created PostgreSQL enum by name
    def e(*values, name):
        return postgresql.ENUM(*values, name=name, create_type=False)

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('username', sa.String(64), nullable=False, unique=True),
        sa.Column('email', sa.String(128), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('role', e('admin', 'user', name='userrole'), nullable=False, server_default='user'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
    )

    # ── app_settings ──────────────────────────────────────────────────────────
    op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('key', sa.String(128), nullable=False, unique=True),
        sa.Column('value', sa.Text, nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── sync_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        'sync_logs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('records_fetched', sa.Integer, server_default='0'),
        sa.Column('records_inserted', sa.Integer, server_default='0'),
        sa.Column('records_updated', sa.Integer, server_default='0'),
        sa.Column('records_skipped', sa.Integer, server_default='0'),
        sa.Column('errors', postgresql.JSONB, nullable=True),
        sa.Column('status', e('running', 'success', 'partial', 'failed', name='syncstatus'), server_default='running'),
        sa.Column('triggered_by', sa.String(64), server_default='manual'),
    )
    op.create_index('ix_sync_logs_category', 'sync_logs', ['category'])
    op.create_index('ix_sync_logs_started_at', 'sync_logs', ['started_at'])

    # ── seasons ───────────────────────────────────────────────────────────────
    op.create_table(
        'seasons',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('year', sa.Integer, nullable=False),
        sa.Column('season_type', sa.String(32), nullable=True),
        sa.Column('name', sa.String(128), nullable=True),
        sa.Column('start_date', sa.Date, nullable=True),
        sa.Column('end_date', sa.Date, nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── teams ─────────────────────────────────────────────────────────────────
    op.create_table(
        'teams',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('abbreviation', sa.String(10), nullable=True),
        sa.Column('city', sa.String(128), nullable=True),
        sa.Column('full_name', sa.String(256), nullable=True),
        sa.Column('conference', sa.String(32), nullable=True),
        sa.Column('division', sa.String(32), nullable=True),
        sa.Column('logo_url', sa.Text, nullable=True),
        sa.Column('primary_color', sa.String(10), nullable=True),
        sa.Column('secondary_color', sa.String(10), nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── coaches ───────────────────────────────────────────────────────────────
    op.create_table(
        'coaches',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('title', sa.String(128), nullable=True),
        sa.Column('experience', sa.Integer, nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── venues ────────────────────────────────────────────────────────────────
    op.create_table(
        'venues',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('city', sa.String(128), nullable=True),
        sa.Column('state', sa.String(64), nullable=True),
        sa.Column('capacity', sa.Integer, nullable=True),
        sa.Column('surface', sa.String(64), nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── players ───────────────────────────────────────────────────────────────
    op.create_table(
        'players',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('first_name', sa.String(128), nullable=True),
        sa.Column('last_name', sa.String(128), nullable=True),
        sa.Column('position', sa.String(32), nullable=True),
        sa.Column('jersey_number', sa.Integer, nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('height', sa.String(16), nullable=True),
        sa.Column('weight', sa.Integer, nullable=True),
        sa.Column('age', sa.Integer, nullable=True),
        sa.Column('college', sa.String(128), nullable=True),
        sa.Column('experience', sa.Integer, nullable=True),
        sa.Column('image_url', sa.Text, nullable=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_players_team_id', 'players', ['team_id'])
    op.create_index('ix_players_position', 'players', ['position'])

    # ── games ─────────────────────────────────────────────────────────────────
    op.create_table(
        'games',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('season_id', sa.Integer, sa.ForeignKey('seasons.id', ondelete='SET NULL'), nullable=True),
        sa.Column('home_team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('away_team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('venue_id', sa.Integer, sa.ForeignKey('venues.id', ondelete='SET NULL'), nullable=True),
        sa.Column('week', sa.Integer, nullable=True),
        sa.Column('season_year', sa.Integer, nullable=True),
        sa.Column('season_type', sa.String(32), nullable=True),
        sa.Column('game_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('home_score', sa.Integer, nullable=True),
        sa.Column('away_score', sa.Integer, nullable=True),
        sa.Column('status', sa.String(64), nullable=True),
        sa.Column('neutral_site', sa.Boolean, server_default='false'),
        sa.Column('broadcast', sa.String(64), nullable=True),
        sa.Column('attendance', sa.Integer, nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_games_week', 'games', ['week'])
    op.create_index('ix_games_season_year', 'games', ['season_year'])
    op.create_index('ix_games_game_date', 'games', ['game_date'])

    # ── scoreboards ───────────────────────────────────────────────────────────
    op.create_table(
        'scoreboards',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False),
        sa.Column('period', sa.Integer, nullable=True),
        sa.Column('home_score', sa.Integer, nullable=True),
        sa.Column('away_score', sa.Integer, nullable=True),
        sa.Column('time_remaining', sa.String(32), nullable=True),
        sa.Column('raw_data', postgresql.JSONB, nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── boxscores ─────────────────────────────────────────────────────────────
    op.create_table(
        'boxscores',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('q1_home', sa.Integer, nullable=True),
        sa.Column('q1_away', sa.Integer, nullable=True),
        sa.Column('q2_home', sa.Integer, nullable=True),
        sa.Column('q2_away', sa.Integer, nullable=True),
        sa.Column('q3_home', sa.Integer, nullable=True),
        sa.Column('q3_away', sa.Integer, nullable=True),
        sa.Column('q4_home', sa.Integer, nullable=True),
        sa.Column('q4_away', sa.Integer, nullable=True),
        sa.Column('ot_home', sa.Integer, nullable=True),
        sa.Column('ot_away', sa.Integer, nullable=True),
        sa.Column('raw_data', postgresql.JSONB, nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── plays ─────────────────────────────────────────────────────────────────
    op.create_table(
        'plays',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer, nullable=True),
        sa.Column('quarter', sa.Integer, nullable=True),
        sa.Column('clock', sa.String(16), nullable=True),
        sa.Column('play_type', sa.String(64), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('yards_gained', sa.Integer, nullable=True),
        sa.Column('home_score', sa.Integer, nullable=True),
        sa.Column('away_score', sa.Integer, nullable=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_plays_game_id', 'plays', ['game_id'])

    # ── player_stats ──────────────────────────────────────────────────────────
    op.create_table(
        'player_stats',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('player_id', sa.Integer, sa.ForeignKey('players.id', ondelete='CASCADE'), nullable=False),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=True),
        sa.Column('season_id', sa.Integer, sa.ForeignKey('seasons.id', ondelete='SET NULL'), nullable=True),
        sa.Column('stat_category', sa.String(64), nullable=False),
        sa.Column('stat_type', sa.String(128), nullable=False),
        sa.Column('value', sa.Numeric(12, 4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('player_id', 'game_id', 'stat_category', 'stat_type', name='uq_player_stats'),
    )
    op.create_index('ix_player_stats_player_id', 'player_stats', ['player_id'])
    op.create_index('ix_player_stats_game_id', 'player_stats', ['game_id'])

    # ── team_stats ────────────────────────────────────────────────────────────
    op.create_table(
        'team_stats',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=True),
        sa.Column('season_id', sa.Integer, sa.ForeignKey('seasons.id', ondelete='SET NULL'), nullable=True),
        sa.Column('stat_category', sa.String(64), nullable=False),
        sa.Column('stat_type', sa.String(128), nullable=False),
        sa.Column('value', sa.Numeric(12, 4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('team_id', 'game_id', 'stat_category', 'stat_type', name='uq_team_stats'),
    )
    op.create_index('ix_team_stats_team_id', 'team_stats', ['team_id'])

    # ── odds ──────────────────────────────────────────────────────────────────
    op.create_table(
        'odds',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(128), nullable=True),
        sa.Column('market_type', sa.String(64), nullable=True),
        sa.Column('home_moneyline', sa.Integer, nullable=True),
        sa.Column('away_moneyline', sa.Integer, nullable=True),
        sa.Column('home_spread', sa.Numeric(5, 1), nullable=True),
        sa.Column('away_spread', sa.Numeric(5, 1), nullable=True),
        sa.Column('spread_juice_home', sa.Integer, nullable=True),
        sa.Column('spread_juice_away', sa.Integer, nullable=True),
        sa.Column('over_under', sa.Numeric(5, 1), nullable=True),
        sa.Column('ou_juice_over', sa.Integer, nullable=True),
        sa.Column('ou_juice_under', sa.Integer, nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_odds_game_id', 'odds', ['game_id'])

    # ── odds_history ──────────────────────────────────────────────────────────
    op.create_table(
        'odds_history',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False),
        sa.Column('odds_type', sa.String(64), nullable=True),
        sa.Column('value', sa.Numeric(10, 2), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── injuries ──────────────────────────────────────────────────────────────
    op.create_table(
        'injuries',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('player_id', sa.Integer, sa.ForeignKey('players.id', ondelete='CASCADE'), nullable=False),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(64), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('practice_status', sa.String(64), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_injuries_player_id', 'injuries', ['player_id'])
    op.create_index('ix_injuries_team_id', 'injuries', ['team_id'])

    # ── depth_charts ──────────────────────────────────────────────────────────
    op.create_table(
        'depth_charts',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('player_id', sa.Integer, sa.ForeignKey('players.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.String(32), nullable=True),
        sa.Column('depth_order', sa.Integer, nullable=True),
        sa.Column('unit', sa.String(32), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('team_id', 'player_id', 'position', 'unit', name='uq_depth_chart'),
    )

    # ── news ──────────────────────────────────────────────────────────────────
    op.create_table(
        'news',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('headline', sa.Text, nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('link', sa.Text, nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('player_id', sa.Integer, sa.ForeignKey('players.id', ondelete='SET NULL'), nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_news_published_at', 'news', ['published_at'])

    # ── drafts ────────────────────────────────────────────────────────────────
    op.create_table(
        'drafts',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('year', sa.Integer, nullable=False),
        sa.Column('round', sa.Integer, nullable=True),
        sa.Column('pick', sa.Integer, nullable=True),
        sa.Column('player_id', sa.Integer, sa.ForeignKey('players.id', ondelete='SET NULL'), nullable=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('player_name', sa.String(256), nullable=True),
        sa.Column('position', sa.String(32), nullable=True),
        sa.Column('college', sa.String(128), nullable=True),
        sa.Column('api_id', sa.String(64), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── parlays ───────────────────────────────────────────────────────────────
    op.create_table(
        'parlays',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(256), nullable=True),
        sa.Column('bet_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('bet_amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('potential_payout', sa.Numeric(10, 2), nullable=True),
        sa.Column('actual_payout', sa.Numeric(10, 2), server_default='0.00'),
        sa.Column('status', e('pending', 'won', 'lost', 'push', 'partial', name='parlaystatustype'), nullable=False, server_default='pending'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_parlays_user_id', 'parlays', ['user_id'])
    op.create_index('ix_parlays_bet_date', 'parlays', ['bet_date'])
    op.create_index('ix_parlays_status', 'parlays', ['status'])

    # ── parlay_legs ───────────────────────────────────────────────────────────
    op.create_table(
        'parlay_legs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('parlay_id', sa.Integer, sa.ForeignKey('parlays.id', ondelete='CASCADE'), nullable=False),
        sa.Column('game_id', sa.Integer, sa.ForeignKey('games.id', ondelete='SET NULL'), nullable=True),
        sa.Column('player_id', sa.Integer, sa.ForeignKey('players.id', ondelete='SET NULL'), nullable=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('leg_type', e('spread', 'moneyline', 'total', 'player_prop', 'team_prop', 'parlay', name='legtype'), nullable=False, server_default='spread'),
        sa.Column('pick', sa.String(512), nullable=False),
        sa.Column('odds', sa.Integer, nullable=True),
        sa.Column('result', e('pending', 'won', 'lost', 'push', name='legresult'), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_parlay_legs_parlay_id', 'parlay_legs', ['parlay_id'])

    # ── documents ─────────────────────────────────────────────────────────────
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('original_filename', sa.String(512), nullable=False),
        sa.Column('file_type', sa.String(32), nullable=True),
        sa.Column('upload_date', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('parsed_status', e('pending', 'success', 'partial', 'failed', name='parsestatus'), server_default='pending'),
        sa.Column('parsed_data', postgresql.JSONB, nullable=True),
        sa.Column('rows_extracted', sa.Integer, server_default='0'),
        sa.Column('rows_skipped', sa.Integer, server_default='0'),
        sa.Column('parser_used', sa.String(64), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
    )
    op.create_index('ix_documents_user_id', 'documents', ['user_id'])

    # ── reports ───────────────────────────────────────────────────────────────
    op.create_table(
        'reports',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('config', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_reports_user_id', 'reports', ['user_id'])


def downgrade():
    for tbl in (
        'reports', 'documents', 'parlay_legs', 'parlays',
        'drafts', 'news', 'depth_charts', 'injuries',
        'odds_history', 'odds', 'team_stats', 'player_stats',
        'plays', 'boxscores', 'scoreboards', 'games',
        'players', 'venues', 'coaches', 'teams',
        'seasons', 'sync_logs', 'app_settings', 'users',
    ):
        op.drop_table(tbl)

    conn = op.get_bind()
    for type_name in ('userrole', 'syncstatus', 'parlaystatustype', 'legtype', 'legresult', 'parsestatus'):
        conn.execute(sa.text(f'DROP TYPE IF EXISTS {type_name}'))
