FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
ENV DATABASE_PATH=/tmp/loyaltyiq.db PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "gunicorn wsgi:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT}"]
