#!/bin/bash
# Sync forecasts from remote server to local
# Usage: ./sync-forecasts.sh

REMOTE_USER="root"
REMOTE_HOST="178.156.244.121"
REMOTE_DIR="/root/prediction-market/data/ensemble_forecasts"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)/data/ensemble_forecasts"

echo "=== Syncing forecasts from ${REMOTE_USER}@${REMOTE_HOST} ==="

rsync -avz "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/" "${LOCAL_DIR}/"

echo ""
echo "=== Sync complete ==="
echo "Local forecasts: $(ls -1 ${LOCAL_DIR}/*.json 2>/dev/null | wc -l) files"
