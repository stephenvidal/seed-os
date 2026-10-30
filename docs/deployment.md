# Deployment — SEED OS

## Docker Compose (self-hosted)
```bash
cp .env.example .env     # set SEED_ADMIN_PASSWORD, SEED_POSTGRES_PASSWORD
docker compose up -d --build
open http://localhost:8080
```
Services: `db` (Postgres 17, data in the `pgdata` volume), `api` (FastAPI,
healthcheck `/healthz`, non-root, read-only FS, 256 MiB limit), `worker` (same
image, runs tasks) and `web` (nginx serving the SPA and proxying `/api`, 64 MiB
limit), and `sandbox` (same image, runs the agent's commands; internal network
only, no secrets, dropped capabilities, 768 MiB limit; ADR-0010). The worker
saves every file a task makes to the `artifacts` volume (`SEED_ARTIFACT_ROOT`,
ADR-0014); the api mounts it read-only for Studio. nginx gives
`/api/v1/previews/` its own headers so the app can frame sandboxed previews
(ADR-0015).

Put a TLS-terminating proxy (Caddy, Traefik, nginx) in front of `web` and set
`SEED_COOKIE_SECURE=true`.

## Production (VPS) — pattern borrowed from `stephenvidal/dustline`

The owner approved reusing dustline's pipeline (D-003). It is in place but
**switched off** until the steps below are done.

| Piece | File | What it does |
|---|---|---|
| CI | `.github/workflows/ci.yml` | On PRs and non-main pushes: backend lint/types/tests, frontend typecheck/lint/format/tests/build, both images built (not pushed) |
| Build and deploy | `.github/workflows/deploy.yml` | On push to `main`: push `ghcr.io/stephenvidal/seed-api` and `seed-web` tagged `latest` and `sha-<7>`; if `DEPLOY_ENABLED`, SSH to the VPS (pinned ED25519 host key), copy `deploy/compose.yaml`, set `SEED_TAG`, `docker compose pull && up -d`, keep two previous releases, check `PUBLIC_URL/healthz` |
| Prod compose | `deploy/compose.yaml` | `db` (Postgres 17, volume `seed_pgdata`, no published port), `api` and `worker` from the API image by tag, saved task files in volume `seed_artifacts` (written by the worker, mounted read-only on the api), web on `127.0.0.1:${SEED_HOST_PORT:-8091}` only, `SEED_COOKIE_SECURE=true`, memory limits, logs capped 10 MB × 3 |

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
   deploy job refuses to start without the admin password; it only ever rewrites
   `SEED_TAG`. (`SEED_SESSION_SECRET` is no longer used since ADR-0009 and can be
   deleted from the file.)
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

### Tasks in production (M3)
The deploy runs Postgres and a worker next to the API. Before the first deploy
that includes them, add to `/opt/seed/.env` on the VPS:

| Variable | Value |
|---|---|
| `SEED_POSTGRES_PASSWORD` | Required. URL-safe random value, e.g. `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` (it is embedded in the database URL, so avoid `@ : / ?`). The deploy job refuses to run without it |
| `SEED_OLLAMA_API_KEY` | Required. Model provider key; the deploy job refuses to run without it. (If it were missing, the API would refuse to create tasks and the worker would exit at start, restarting at most 5 times) |
| `SEED_DEFAULT_MODEL` | `deepseek-v4.1-flash` (ADR-0007) |

The database is created on first start and migrated by the API and worker. The
password only takes effect when the volume is first initialised; changing it
later means changing it inside Postgres too.

Backups are manual until M9:
`docker compose exec -T db pg_dump -U seed seed | gzip > seed-$(date +%F).sql.gz`
(run in `/opt/seed`). Restore into an empty database with
`gunzip -c FILE | docker compose exec -T db psql -U seed seed`.

### Telegram (M8, optional)
The `gateway` service sends your notifications to Telegram. It exits at start while
no token is set. To switch it on:
1. In Telegram, message @BotFather, send `/newbot`, and copy the token it gives.
2. Add `SEED_TELEGRAM_BOT_TOKEN=<token>` and `SEED_PUBLIC_URL=https://seed.nsystems.live`
   to `/opt/seed/.env`, then run `docker compose up -d gateway` in `/opt/seed`.
3. Message your bot. It replies with your chat's id. Add `SEED_TELEGRAM_CHAT_ID=<id>`
   to `.env` and run `docker compose up -d gateway` again.
The token is a secret like the others: vault and `.env` only.

### Secrets handling
`SEED_ADMIN_PASSWORD` and `SEED_POSTGRES_PASSWORD` live in the encrypted vault
(`vault.py get SEED_ADMIN_PASSWORD` on golden-eye) and in `/opt/seed/.env` on the
VPS. They never appear in the repository, in workflow logs, or in chat.

Since ADR-0009 the admin password in `.env` is only read while the database has
no users. To change a password, run on the VPS (in `/opt/seed`)
`docker compose exec api python -m seed_api.users set-password admin` (it prompts;
the user is signed out everywhere), then update the vault. Rotating the Postgres
password means `ALTER USER` inside Postgres, then both places, then a restart.

Rollback: set `SEED_TAG` in `/opt/seed/.env` to an earlier `sha-…` and run
`docker compose up -d` there.

## Requirements (measured)
M1 idle: api ≈ 40 MiB, web ≈ 5 MiB RSS. M3 stack, after one task (2026-10-28,
`docker stats`): api 47.7 MiB, db 23.3 MiB, web 4.7 MiB; the worker runs the same
image as the api. The sandbox adds up to 768 MiB under load (its workspaces are
a 256 MiB tmpfs); idle it is about the size of the api. Disk: `postgres:17-alpine` is 424 MB uncompressed, plus the
data volume (48 MB fresh). No GPU.

## Backups
Postgres: manual `pg_dump`, see "Tasks in production" above. Artifacts: the
`seed_artifacts` volume holds file content and Postgres holds which version is
which, so back up both together (for example, `pg_dump`, then
`docker run --rm -v seed_artifacts:/a -v "$PWD":/b alpine tar czf /b/artifacts.tgz -C /a .`).
Automated backups are part of M9.
