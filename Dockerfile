# Use official Python image
FROM python:3.9-slim AS base

# Install FFmpeg and curl (for healthcheck)
RUN apt-get update && \
    apt-get install -y ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and entrypoint
COPY app.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Create directory for temporary files
RUN mkdir -p /tmp/ffmpeg_api && \
    chmod 777 /tmp/ffmpeg_api

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV WORKERS=2
ENV THREADS=2
ENV TIMEOUT=600        
ENV FFMPEG_TIMEOUT=0   

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8000/health", "||", "exit", "1"]

# Use entrypoint script
ENTRYPOINT ["./entrypoint.sh"]