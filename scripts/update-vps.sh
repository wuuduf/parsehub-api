#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose -f compose.prod.yaml pull
docker compose -f compose.prod.yaml up -d --remove-orphans
docker image prune -f
docker compose -f compose.prod.yaml ps
