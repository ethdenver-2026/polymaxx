#!/bin/bash
# Deploy forecast collector to remote server
# Usage: ./deploy.sh

set -e

REMOTE_USER="root"
REMOTE_HOST="178.156.244.121"
REMOTE_DIR="/root/prediction-market"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deploying to ${REMOTE_USER}@${REMOTE_HOST} ==="

# Create remote directory structure
echo "Creating remote directories..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "mkdir -p ${REMOTE_DIR}/data/ensemble_forecasts ${REMOTE_DIR}/logs"

# Sync producer code (excluding tests, __pycache__, etc.)
echo "Syncing producer code..."
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude 'tests/' \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '*.egg-info' \
    "${LOCAL_DIR}/producer/" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/producer/"

# Sync pyproject.toml for dependencies
echo "Syncing configuration files..."
rsync -avz "${LOCAL_DIR}/producer/pyproject.toml" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/producer/"

# Setup Python environment and install dependencies
echo "Setting up Python environment..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << 'REMOTE_SETUP'
set -e
cd ~/prediction-market

# Ensure python3-venv is installed (for Ubuntu/Debian)
echo "Installing python3-venv if needed..."
apt-get update -qq && apt-get install -y -qq python3.12-venv python3-pip 2>/dev/null || true

# Remove broken venv if it exists
if [ -d ".venv" ] && [ ! -f ".venv/bin/pip" ]; then
    echo "Removing broken venv..."
    rm -rf .venv
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate and install dependencies
source .venv/bin/activate
pip install --upgrade pip

# Install dependencies for forecast collection
pip install httpx structlog pydantic pydantic-settings typer sqlalchemy

echo "Python environment ready!"
REMOTE_SETUP

# Install crontab
echo "Installing crontab..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << 'REMOTE_CRON'
# Create the cron job entry
CRON_CMD="0 */6 * * * cd /root/prediction-market && { echo \"=== \$(date) ===\"; .venv/bin/python -m producer.signal_producer.cli collect --max-days 4; } >> /root/prediction-market/logs/ensemble_collect.log 2>&1"

# Check if cron entry already exists
(crontab -l 2>/dev/null | grep -v "signal_producer.cli collect"; echo "$CRON_CMD") | crontab -

echo "Crontab installed:"
crontab -l | grep ensemble
REMOTE_CRON

# Test the collection
echo ""
echo "=== Testing forecast collection ==="
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ~/prediction-market && .venv/bin/python -m producer.signal_producer.cli collect --days 1 --cities nyc 2>&1 | head -20"

echo ""
echo "=== Deployment complete! ==="
echo "Logs: ssh ${REMOTE_USER}@${REMOTE_HOST} 'tail -f ~/prediction-market/logs/ensemble_collect.log'"
echo "Data: ssh ${REMOTE_USER}@${REMOTE_HOST} 'ls -la ~/prediction-market/data/ensemble_forecasts/'"
