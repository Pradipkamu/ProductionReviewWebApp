FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY templates ./templates
COPY alembic.ini ./
COPY alembic ./alembic
RUN mkdir -p /app/uploads /app/backups
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
