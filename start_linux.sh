#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
docker compose up --build -d
echo "Application: http://localhost:5173"
echo "API docs:    http://localhost:8000/docs"
