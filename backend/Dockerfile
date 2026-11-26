# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-impress fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    --default-timeout=300 \
    --retries=10 \
    -r requirements.txt
COPY app ./app
COPY templates ./templates
COPY alembic.ini ./
COPY alembic ./alembic
RUN mkdir -p /app/uploads /app/backups
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
