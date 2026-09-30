#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 configure_env.py
docker compose up --build -d
echo "Application: http://localhost:5173"
echo "API docs:    http://localhost:8000/docs"
