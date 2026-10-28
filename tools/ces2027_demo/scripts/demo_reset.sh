#!/bin/bash
# Bring the demo on this server back to its initial state without an agent
# (design section 6.4). Every step is one the README describes by hand.
#
#   scripts/demo_reset.sh app                                booth app server, data kept
#   scripts/demo_reset.sh --wipe app                         also delete this server's data volumes
#   scripts/demo_reset.sh db                                 booth db server
#   scripts/demo_reset.sh app db                             one server with both roles (company)
#   scripts/demo_reset.sh local scenario/script.sample.json  Mac
#
# Arguments: the compose profiles of this server (the same words as in
# `docker compose --profile`), --wipe, and optionally the script file
# (default scenario/script.json).
#
#   1. --wipe only: `docker compose down -v` removes the containers and the data
#      volumes of this server (PostgreSQL, Qdrant, Open WebUI with its accounts
#      and chats), which is the state of a fresh install.
#   2. `docker compose up -d --force-recreate --wait`: new containers from the
#      pinned images and the current .env, then wait for every healthcheck.
#   3. When this server runs the app (or local) profile: the setup script
#      (accounts, Pipe, models), the load script (a new project with the past
#      sessions and the sidebar chats) and the check script.
#
# With separate servers run it on the db server first and on the app server
# last. The LLM and embedding servers are not part of it; they come up on their own.
set -euo pipefail

demo=$(cd "$(dirname "$0")/.." && pwd)
wipe=
script=$demo/scenario/script.json
profiles=()
for arg in "$@"; do
  case $arg in
    --wipe) wipe=yes ;;
    *.json) [[ $arg = /* ]] && script=$arg || script=$PWD/$arg ;;
    *) profiles+=(--profile "$arg") ;;
  esac
done
if [[ ${#profiles[@]} -eq 0 ]]; then
  echo "usage: demo_reset.sh [--wipe] <profile>... [script.json]   (profiles: app, db, local)" >&2
  exit 2
fi

cd "$demo/deploy"   # docker compose reads .env here
if [[ $wipe ]]; then
  echo "== removing the containers and data volumes of this server"
  docker compose "${profiles[@]}" down -v
fi
echo "== starting the containers and waiting for their healthchecks"
docker compose "${profiles[@]}" up -d --force-recreate --wait --wait-timeout 900

case " $* " in
  *" app "* | *" local "*)
    cd "$demo"
    echo "== setup: accounts, Pipe, models"
    python3 scripts/setup_openwebui.py
    echo "== load: $script"
    python3 scripts/load_scenario.py "$script"
    echo "== check"
    python3 scripts/demo_check.py "$script"
    ;;
  *)
    echo "== no app profile on this server: run demo_reset.sh on the app server next"
    ;;
esac
