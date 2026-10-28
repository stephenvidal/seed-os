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

## Production (VPS) — pattern borrowed from `stephenvidal/dustline`

The owner approved reusing dustline's pipeline (D-003). It is in place but
**switched off** until the steps below are done.

| Piece | File | What it does |
|---|---|---|
| CI | `.github/workflows/ci.yml` | On PRs and non-main pushes: backend lint/types/tests, frontend typecheck/lint/format/tests/build, both images built (not pushed) |
| Build and deploy | `.github/workflows/deploy.yml` | On push to `main`: push `ghcr.io/stephenvidal/seed-api` and `seed-web` tagged `latest` and `sha-<7>`; if `DEPLOY_ENABLED`, SSH to the VPS (pinned ED25519 host key), copy `deploy/compose.yaml`, set `SEED_TAG`, `docker compose pull && up -d`, keep two previous releases, check `PUBLIC_URL/healthz` |
| Prod compose | `deploy/compose.yaml` | Images by tag, web on `127.0.0.1:${SEED_HOST_PORT:-8091}` only, `SEED_COOKIE_SECURE=true`, memory limits, logs capped 10 MB × 3 |

Both workflows run on a self-hosted runner with labels `self-hosted, golden-eye`,
because hosted minutes are blocked on this account. Keep `runs-on`, the fork
guard in `ci.yml`, and `timeout-minutes` on every job (dustline `docs/CI.md`
explains why).

### To switch it on (owner)
1. **Runner:** register a runner for `stephenvidal/seed-os` on golden-eye with
   labels `self-hosted,golden-eye` (runners are per-repository; dustline's runner
   will not pick up seed-os jobs). Until then, CI jobs sit queued.
2. **VPS folder:** create `/opt/seed` owned by the deploy user, with `.env`
   (mode 600) containing at least `SEED_ADMIN_PASSWORD` and
   `SEED_SESSION_SECRET`. The deploy job refuses to start without them; it
   only ever rewrites `SEED_TAG`.
3. **Tunnel:** route a public hostname to `http://127.0.0.1:8091` in the
   Cloudflare tunnel. Host ports 8080 and 8090 are already taken.
4. **Repo settings:** secrets `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`,
   `VPS_HOST_FINGERPRINT` (and `VPS_PORT` if not 22); variables `PUBLIC_URL`,
   optionally `DEPLOY_PATH`; then set `DEPLOY_ENABLED=true`.
5. GHCR packages are private; the VPS must already be logged in to ghcr.io (it is
   for dustline).

Rollback: set `SEED_TAG` in `/opt/seed/.env` to an earlier `sha-…` and run
`docker compose up -d` there.

## Requirements (measured)
Idle: api ≈ 40 MiB, web ≈ 5 MiB RSS. 1 vCPU / 512 MiB is enough for M1. Storage:
images only (no persistent data until M3). No GPU.

## Backups
Nothing to back up until Postgres and artifact storage land (M3/M6).
