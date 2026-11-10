"""Production entry point: gunicorn wsgi:app"""
from pathlib import Path

from app import config, create_app

Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
app = create_app()
