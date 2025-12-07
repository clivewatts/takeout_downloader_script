FROM python:3.11-slim

LABEL maintainer="Google Takeout Downloader"
LABEL description="Web interface for downloading Google Takeout archives"

# Set working directory
WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY takeout.py .
COPY google_takeout_web.py .

# Create downloads directory
RUN mkdir -p /downloads

# Environment variables
ENV OUTPUT_DIR=/downloads
ENV PARALLEL_DOWNLOADS=6
ENV FILE_COUNT=100
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Run the web server
CMD ["python", "google_takeout_web.py", "--host", "0.0.0.0", "--port", "5000"]
