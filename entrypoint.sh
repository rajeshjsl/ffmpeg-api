#!/bin/bash
exec gunicorn app:app \
    --worker-class gthread \
    --workers "${WORKERS}" \
    --threads "${THREADS}" \
    --timeout "${TIMEOUT}" \
    --bind 0.0.0.0:8000