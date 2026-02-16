#!/usr/bin/env bash
# scripts/test.sh — Use .venv (create if missing), install deps, run pytest. Exit 1 on test failure.
# Use this before skill:archive to ensure tests pass.
# Usage: ./scripts/test.sh   or   ./scripts/test.sh -v tests/unit/test_dice_check.py
set -e

cd "$(dirname "$0")/.."
ROOT="$PWD"
VENV="${VENV:-$ROOT/.venv}"

# Create venv if it doesn't exist
if [[ ! -d "$VENV" ]]; then
    echo "Creating venv at $VENV..."
    python3 -m venv "$VENV"
fi

# Activate and ensure project + dev deps are installed
source "$VENV/bin/activate"
if ! python -c "import bot.dice_check" 2>/dev/null; then
    echo "Installing project and dev dependencies..."
    pip install -e ".[dev]" -q
fi

echo "Running pytest..."
python -m pytest tests/ "$@"
