#!/usr/bin/env sh
set -eu

# Run database migrations on startup (fresh Render deploys have an empty schema).
# Alembic reads DATABASE_URL from app.config via migrations/env.py.
echo "Verity: running Alembic migrations..."
alembic upgrade head

# Optional: seed default demo accounts.
# Safe to run multiple times (seed.py uses ON CONFLICT DO NOTHING).
if [ "${SEED_ON_STARTUP:-false}" = "true" ]; then
  echo "Verity: seeding default accounts (SEED_ON_STARTUP=true)..."
  python seed.py
fi

echo "Verity: starting API server..."

# Render sets PORT; default to 8000 for local Docker runs.
PORT="${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers

