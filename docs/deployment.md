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

Both workflows run on GitHub-hosted `ubuntu-latest` runners. The repository is
**public**, so standard-hosted minutes are unmetered; earlier revisions used a
self-hosted runner on golden-eye because the account's spending limit blocked
hosted minutes for private repos. Consequences of going public that the workflows
carry: keep the fork guard in `ci.yml` (a fork PR must never execute a job that can
reach secrets) and keep `timeout-minutes` on every job.

### To switch it on (owner)
Staging status as of 2026-10-28: items 1–4 are done and verified; only the final
flip in item 5 remains.

1. ~~Runner~~ — done. The seed-os self-hosted runner was used for the first real
   runs and then retired when the repository went public and CI moved to hosted
   runners (`gh api -X DELETE repos/stephenvidal/seed-os/actions/runners/<id>`).
2. **VPS folder** — done. `/opt/seed` exists, owned by `deploy`, with `.env`
   (mode 600, owner `deploy`) holding `SEED_ADMIN_USERNAME`, `SEED_ADMIN_PASSWORD`,
   `SEED_SESSION_SECRET`, `SEED_COOKIE_SECURE=true`, `SEED_HOST_PORT=8091`. The
   deploy job refuses to start without the password and session secret; it only
   ever rewrites `SEED_TAG`.
3. **Tunnel** — done. DNS `seed.nsystems.live` is a proxied CNAME to tunnel
   `d0a6e41c-…` (the `*.nsystems.live` wildcard points at a different tunnel that
   would answer 404), and `/etc/cloudflared/srv1388017-files.yml` carries
   `seed.nsystems.live -> http://127.0.0.1:8091` ahead of the 404 catch-all.
   Verified: the hostname answers 502, which is the tunnel correctly reaching a
   port with nothing on it yet. Rebuild the ingress list and restart
   `cloudflared-srv1388017-files.service` if it is ever lost.
4. **Repo settings** — secrets `VPS_HOST`, `VPS_USER`, `VPS_PORT`, `VPS_SSH_KEY`,
   `VPS_HOST_FINGERPRINT` and variables `PUBLIC_URL=https://seed.nsystems.live`,
   `DEPLOY_PATH=/opt/seed` are all set. The SSH key is dustline's deploy key
   (`deploy@31.187.72.46`), verified from the runner side to log in, write
   `/opt/seed` and run `docker compose` v5.5.1. GHCR read access is already present
   at `/home/deploy/.docker/config.json` (private pull verified).
5. **The flip:** set the repository variable `DEPLOY_ENABLED=true`. Nothing deploys
   before that, and the first deploy needs an image, so it also needs a merge to
   `main` (the build job runs on `main` pushes).

### Secrets handling
`SEED_ADMIN_PASSWORD` and `SEED_SESSION_SECRET` live in the encrypted vault
(`vault.py get SEED_ADMIN_PASSWORD` on golden-eye) and in `/opt/seed/.env` on the
VPS. They never appear in the repository, in workflow logs, or in chat. Rotating
them means updating both places and restarting the stack.

Rollback: set `SEED_TAG` in `/opt/seed/.env` to an earlier `sha-…` and run
`docker compose up -d` there.

## Requirements (measured)
Idle: api ≈ 40 MiB, web ≈ 5 MiB RSS. 1 vCPU / 512 MiB is enough for M1. Storage:
images only (no persistent data until M3). No GPU.

## Backups
Nothing to back up until Postgres and artifact storage land (M3/M6).
