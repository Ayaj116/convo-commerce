# For more information, please refer to https://aka.ms
FROM python:3-slim

EXPOSE 8000

# Keeps Python from generating .pyc files in the container
ENV PYTHONTONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Set the working directory early so dependencies locate properly
WORKDIR /app

# Install pip requirements
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy application code into container
COPY . /app

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# FIXED: Wrapped command in "sh -c" shell syntax to allow dynamic environment variable expansion.
# FIXED: Backward slash changed to dot notation for standard module pathing.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} -k uvicorn.workers.UvicornWorker src.gateway.app:app"]
