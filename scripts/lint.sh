#!/usr/bin/env bash
# scripts/lint.sh — Run ruff and pyright. Exit 1 on any failure.
# Usage: ./scripts/lint.sh   or   bash scripts/lint.sh
set -e

echo "Running ruff check..."
ruff check .

echo "Running ruff format check..."
ruff format --check .

echo "Running pyright..."
pyright

echo "✓ All checks passed!"
