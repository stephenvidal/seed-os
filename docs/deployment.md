# Deployment — SEED OS

## Docker Compose (self-hosted)
```bash
cp .env.example .env     # set SEED_ADMIN_PASSWORD and SEED_SESSION_SECRET
docker compose up -d --build
open http://localhost:8080
```
Services: `api` (FastAPI, healthcheck `/healthz`, non-root, read-only FS,
256 MiB limit) and `web` (nginx serving the SPA and proxying `/api`, 64 MiB
limit). Postgres, worker, and sandbox services are added in M3.

Put a TLS-terminating proxy (Caddy, Traefik, nginx) in front of `web` and set
`SEED_COOKIE_SECURE=true`.

## Requirements (measured)
Idle: api ≈ 40 MiB, web ≈ 5 MiB RSS. 1 vCPU / 512 MiB is enough for M1. Storage:
images only (no persistent data until M3). No GPU.

## Backups
Nothing to back up until Postgres and artifact storage land (M3/M6).
