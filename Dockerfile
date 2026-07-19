# WeatherBet — paper bot + read-only dashboard
# Same image, different command per service (see docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.json .
COPY weatherbet.py .
COPY weatherbet/ weatherbet/
COPY dashboard/ dashboard/

RUN mkdir -p data/markets

# Dashboard listens here when that service is selected
EXPOSE 8765

# Default: long-running paper bot. Compose overrides for the dashboard.
CMD ["python", "weatherbet.py"]
