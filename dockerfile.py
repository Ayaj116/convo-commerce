FROM python:3.12-slim

WORKDIR /app

# Copy dependencies first to leverage Docker caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all folders (keeps your exact folder structure intact)
COPY . .

# Explicitly launch the gateway app using Render's dynamic port
CMD uvicorn src.gateway.app:app --host 0.0.0.0 --port $PORT