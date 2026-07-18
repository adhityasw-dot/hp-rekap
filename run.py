"""Jalankan lokal: python run.py | Production: gunicorn/uvicorn via Dockerfile."""
import os

import uvicorn

from app.config import HOST, PORT

if __name__ == "__main__":
    reload = os.environ.get("RELOAD", "1" if os.environ.get("ENV", "development") == "development" else "0") == "1"
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=reload and os.environ.get("ENV", "development") != "production",
    )
