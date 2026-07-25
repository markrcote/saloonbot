#!/bin/sh
# Keep the staging host's checkout in sync with origin/main and apply any
# compose changes. Watchtower already auto-updates *images*, but it reuses
# each container's existing config, so compose-file changes (ports, env,
# new services) never land without a git pull + `compose up` — this script
# closes that gap. Runs on the staging host via a systemd timer
# (saloonbot-autodeploy.timer); see containers/saloonbot.md in the
# home-network repo. Staging only — prod is deployed manually after
# changes have soaked here.
set -eu
cd "$(dirname "$0")"

git fetch origin main
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
    exit 0
fi

echo "Updating $(git rev-parse --short HEAD) -> $(git rev-parse --short origin/main)"
git merge --ff-only origin/main
docker compose -f compose.staging.yml up -d
