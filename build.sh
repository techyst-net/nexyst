#!/usr/bin/env bash
# Build this app's images and push them to the registry.
#
#   ./build.sh          build and push
#   ./build.sh --build  build only
#
# Registry settings come from .registry.env beside this script.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .registry.env ] || { echo "missing .registry.env (REGISTRY, DOCKERHUB_USER, TAG)"; exit 1; }
set -a; . ./.registry.env; set +a
: "${DOCKERHUB_USER:?set DOCKERHUB_USER in .registry.env}"

docker compose --env-file .registry.env -f compose.build.yaml build
[ "${1:-}" = "--build" ] && exit 0
docker compose --env-file .registry.env -f compose.build.yaml push
