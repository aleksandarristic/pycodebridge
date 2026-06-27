FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        bat \
        fd-find \
        gh \
        jq \
        less \
        procps \
        ripgrep \
        git \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex @anthropic-ai/claude-code @google/gemini-cli

WORKDIR /app

COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

RUN useradd -m -u 1000 bridge && chown -R bridge:bridge /app
USER bridge

ENTRYPOINT ["python", "-m", "cmd.bridge"]
CMD ["-config", "/app/config.docker.yaml"]
