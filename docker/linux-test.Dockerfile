FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    git \
    curl \
    ca-certificates \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
