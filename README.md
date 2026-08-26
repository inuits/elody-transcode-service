<p align="center">
  <a href="https://elody.eu"><img src="https://elody.eu/images/logo.svg" alt="Elody" width="96" /></a>
</p>

<p align="center">Part of <a href="https://elody.eu">Elody</a> — the open semantic data platform.<br /><a href="https://docs.elody.eu">Documentation</a> · <a href="https://elody.eu">Website</a></p>

# Inuits DAMS Transcode Service

Flask service that converts mediafiles between formats (JPEG, MP3, MP4, PDF) and bundles multiple mediafiles into downloadable zips. Triggered by other Elody services over HTTP or by RabbitMQ events; pulls source files from storage-api and pushes transcodes back.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/transcode/jpeg` | Produce a JPEG transcode for the given mediafile(s). |
| `POST` | `/transcode/mp3` | Produce an MP3 transcode. |
| `POST` | `/transcode/mp4` | Produce an MP4 transcode. |
| `POST` | `/transcode/pdf` | Produce a PDF transcode. |
| `POST` | `/transcode/zip` | Bundle mediafiles into a zip archive and stream it back. Used by the PWA's "download selection as zip" flow via baseGraphql's `/api/download/zip/:id` proxy. |
| `GET`  | `/spec/dams-transcode-service.json` | OpenAPI spec. |
| `GET`  | `/spec/dams-transcode-service-events.html` | AsyncAPI spec for the RabbitMQ events. |
| `GET`  | `/health` | Liveness probe. |

## Layout

- `api/app.py` — Flask + Flask-RESTful bootstrap and route registration.
- `api/transcoder.py` — core transcode logic (ffmpeg / imagemagick / etc. wrappers).
- `api/resources/transcode.py` — per-format resource classes (`JpegTranscode`, `MP3Transcode`, `MP4Transcode`, `PDFTranscode`, `ZipTranscode`).
- `api/resources/queues.py` — RabbitMQ consumers/publishers for event-driven transcode jobs.
- `api/resources/spec.py` — OpenAPI + AsyncAPI spec endpoints.
- `api/policy_factory.py` — authorization policy hookup.
- `api/rabbit.py` — AMQP client setup.
- `api/apps/` — per-tenant app configuration.
- `docker/` — container build (includes ffmpeg + imagemagick).
- `scripts/` — operational helpers.

## Local setup

The [elody-common](https://gitlab.inuits.io/rnd/inuits/elody/elody-common) repository ships the shared docker-compose stack. Enable this service via `docker-compose-include-transcode-service.yml`.

## Dependencies

Python 3, Flask, Flask-RESTful, `amqpstorm-flask` (RabbitMQ), Elody client library, plus system-level `ffmpeg` and `imagemagick` binaries in the container. Full pin list in `requirements.txt`.
