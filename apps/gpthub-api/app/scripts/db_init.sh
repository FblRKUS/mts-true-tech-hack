#!/usr/bin/env sh
set -eu

echo "[db-init] start"

if [ -f "/app/alembic.ini" ] && command -v alembic >/dev/null 2>&1; then
  echo "[db-init] alembic config found, running migrations"
  alembic upgrade head
  echo "[db-init] migrations completed"
else
  echo "[db-init] alembic config not found, skip migrations"
fi

echo "[db-init] done"
