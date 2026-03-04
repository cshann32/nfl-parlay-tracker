#!/bin/sh
# Docker entrypoint — waits for Postgres, runs migrations, starts the app.
set -e

echo "[entrypoint] Waiting for PostgreSQL..."
until pg_isready -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" -U "${DB_USER:-nfl}" -q; do
  sleep 1
done
echo "[entrypoint] PostgreSQL is ready."

echo "[entrypoint] Applying database migrations..."
flask db upgrade

echo "[entrypoint] Seeding default app settings..."
flask create-settings || true

echo "[entrypoint] Starting application..."
exec "$@"
