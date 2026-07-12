# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3-slim

# Railway injects a dynamic port at runtime. This tells Docker what to look for.
EXPOSE 8000

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Set the working directory early so dependencies install in the correct context
WORKDIR /app

# Install pip requirements
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy the application source code into the container
COPY . /app

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# FIX 1: Changed backward slash to a dot (.) for module path resolution.
# FIX 2: Wrapped command in a shell block to dynamically read Railway's ${PORT} variable.
# NOTE: Make sure 'gunicorn' is explicitly written in your requirements.txt file.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} -k uvicorn.workers.UvicornWorker src.gateway.app:app"]
