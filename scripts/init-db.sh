#!/usr/bin/env bash
# The image sources non-executable .sh files too; mode bits on Windows are harmless.
set -euo pipefail
psql --no-psqlrc --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --file /iris-sql/bootstrap.sql
