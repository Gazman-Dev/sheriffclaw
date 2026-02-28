FROM python:3.11-slim
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash git curl ca-certificates build-essential bubblewrap sudo \
 && rm -rf /var/lib/apt/lists/*
# We will mount the volume at runtime via docker-compose, so no need to COPY here
