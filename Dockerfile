FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV=production \
    DATA_DIR=/data \
    PORT=8000

RUN mkdir -p /data \
    && apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

# Catatan: JANGAN pakai directive VOLUME di sini.
# Railway menolak Dockerfile yang berisi VOLUME.
# Persistent storage: pasang Railway Volume di dashboard, mount path /data.

EXPOSE 8000

# Railway/Render inject $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
