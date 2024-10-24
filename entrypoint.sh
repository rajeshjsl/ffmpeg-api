#!/bin/bash
exec gunicorn \
    --workers "${WORKERS}" \
    --threads "${THREADS}" \
    --timeout "${TIMEOUT}" \
    --bind 0.0.0.0:8000 \
    --log-level info \
    --access-logfile - \
    --error-logfile - \
    "app:app"