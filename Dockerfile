# Use official Python image
FROM python:3.9-slim AS base

# Install FFmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Create directory for temporary files
RUN mkdir -p /tmp/ffmpeg_api && \
    chmod 777 /tmp/ffmpeg_api

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV WORKERS=2
ENV THREADS=2
ENV TIMEOUT=300

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with gunicorn
CMD gunicorn \
    --workers ${WORKERS} \
    --threads ${THREADS} \
    --timeout ${TIMEOUT} \
    --bind 0.0.0.0:8000 \
    --log-level info \
    --access-logfile - \
    --error-logfile - \
    app:app