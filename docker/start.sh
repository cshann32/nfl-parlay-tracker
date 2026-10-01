#!/bin/sh
# Wait for Docker Desktop to be ready, then start the stack.
until docker info > /dev/null 2>&1; do
  sleep 2
done
exec docker compose -f /Users/biggis/nfl-parlay-tracker/docker/compose.hub.yml up -d
