FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libpq-dev \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first — separate layer so code changes don't bust cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Runtime directories + non-root user
RUN mkdir -p /app/logs /app/uploads \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app \
    && chmod +x /app/docker/entrypoint.sh

USER appuser

EXPOSE 5000

ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Production: Gunicorn with 2 workers, 2 threads each
# Dev override: ["flask", "run", "--host=0.0.0.0", "--port=5000"]
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "run:app"]
