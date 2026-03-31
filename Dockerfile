# Development Dockerfile with hot reload
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install watchfiles

# Create logs and data directories
RUN mkdir -p logs data

# Expose port
EXPOSE 9898

# Development command with hot reload
CMD ["uvicorn", "src.server.app:app", "--host", "0.0.0.0", "--port", "9898", "--reload"]
