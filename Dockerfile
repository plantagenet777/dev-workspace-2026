# Stable base image
FROM python:3.11-slim

# Build dependencies for scipy/numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for logs, data, certs, models
RUN mkdir -p logs data certs models

# Train model at build time (if models/ is empty)
RUN python train_and_save.py

# Avoid .pyc and unbuffered output
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

# Run smoke test then main application
CMD ["sh", "-c", "python tests/test_smoke.py && python app/main_app.py"]
