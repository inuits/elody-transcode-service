ARG UV_IMAGE_PREFIX=ghcr.io

FROM ${UV_IMAGE_PREFIX}/astral-sh/uv:0.12.1 as uv_binary

### Base stage
FROM python:3.13-alpine AS base-stage
COPY --from=uv_binary /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV FLASK_APP=app.py

RUN apk update && apk add --no-cache ffmpeg git && adduser --disabled-password --home /app --shell /bin/bash app

USER app
WORKDIR /app

COPY docker/entrypoint*.sh /
COPY requirements.txt ./
COPY requirements_dev.txt ./

RUN echo "export PATH=${PATH}:/app/.local/bin" >> .bashrc

ENTRYPOINT ["/entrypoint_uv.sh"]

### Development stage
FROM base-stage AS development-stage

ENV APP_ENV=dev

COPY docker/pip.conf /etc

RUN uv venv && uv pip install --no-cache-dir -r requirements.txt -r requirements_dev.txt

EXPOSE 5000

### Build stage
FROM base-stage AS build-stage

COPY docker/pip.conf /etc
COPY api ./api

RUN uv venv && uv pip install --no-cache-dir -r requirements.txt

### Production stage
FROM base-stage AS production-stage

ENV APP_ENV=prod

COPY --from=build-stage /app /app

ENV GUNICORN_CMD_ARGS="--workers=3"

EXPOSE 8000
