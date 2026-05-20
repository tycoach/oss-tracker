#!/usr/bin/env bash
# provision.sh — OSS Tracker
# Run this after every MiniSky restart to recreate Pub/Sub topics and subscriptions.
# MiniSky loses state on restart — this script is idempotent (safe to run multiple times).
#
# Usage:
#   chmod +x provision.sh   # first time only
#   ./provision.sh

set -euo pipefail

MINISKY_HOST="${MINISKY_HOST:-http://localhost:8080}"
PROJECT_ID="${MINISKY_PROJECT_ID:-local-dev-project}"
BASE="$MINISKY_HOST/v1/projects/$PROJECT_ID"

echo "=================================================="
echo " OSS Tracker — MiniSky Provisioner"
echo " Host   : $MINISKY_HOST"
echo " Project: $PROJECT_ID"
echo "=================================================="

# ── Wait for MiniSky to be ready ──────────────────────
echo ""
echo "→ Waiting for MiniSky..."
for i in $(seq 1 15); do
  if curl -s --max-time 2 "$MINISKY_HOST" > /dev/null 2>&1; then
    echo "  ✓ MiniSky is up"
    break
  fi
  echo "  ... ($i/15)"
  sleep 2
  if [ $i -eq 15 ]; then
    echo "  ✗ MiniSky not reachable after 30s. Is it running?"
    exit 1
  fi
done

# ── Helper functions ───────────────────────────────────
create_topic() {
  local topic=$1
  local response
  response=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/topics/$topic")
  if [ "$response" = "200" ]; then
    echo "  ✓ topic $topic created"
  elif [ "$response" = "409" ]; then
    echo "  ~ topic $topic already exists"
  else
    echo "  ✗ topic $topic failed (HTTP $response)"
  fi
}

create_subscription() {
  local sub=$1
  local topic=$2
  local response
  response=$(curl -s -o /dev/null -w "%{http_code}" \
    -X PUT "$BASE/subscriptions/$sub" \
    -H "Content-Type: application/json" \
    -d "{\"topic\":\"projects/$PROJECT_ID/topics/$topic\"}")
  if [ "$response" = "200" ]; then
    echo "  ✓ subscription $sub → $topic"
  elif [ "$response" = "409" ]; then
    echo "  ~ subscription $sub already exists"
  else
    echo "  ✗ subscription $sub failed (HTTP $response)"
  fi
}

# ── Topics ─────────────────────────────────────────────
echo ""
echo "→ Creating topics..."
create_topic "raw.git_repos"
create_topic "raw.npm_packages"
create_topic "raw.hn_stories"

# ── Subscriptions ──────────────────────────────────────
echo ""
echo "→ Creating subscriptions..."
create_subscription "raw.git_repos-sub"    "raw.git_repos"
create_subscription "raw.npm_packages-sub" "raw.npm_packages"
create_subscription "raw.hn_stories-sub"   "raw.hn_stories"

# ── Done ───────────────────────────────────────────────
echo ""
echo "=================================================="
echo " ✓ Provisioning complete. Ready to run:"
echo "   python data-generator/fetch_oss.py"
echo "=================================================="