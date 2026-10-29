# ADR-0015 — Studio serves saved files sandboxed, and previews through short-lived links

**Status:** Accepted (2026-10-29)

**Context:** Studio shows the files tasks make (ADR-0014): source, images, and
HTML apps the agent wrote. WS-6 requires HTML to run isolated from the privileged
origin. The app runs on one origin (`seed.nsystems.live`), and a second origin
would need DNS, a tunnel route and a certificate per deployment.

**Options**
1. A separate preview origin (subdomain).
2. Same origin, but every served file carries a CSP `sandbox`, so the browser
   gives it an opaque origin: no cookies, no storage, no access to the app.
3. Render HTML in the app's DOM after sanitising.

**Decision:** Option 2.

- **Version content** (`GET /api/v1/artifacts/{id}/versions/{n}/content`) needs a
  signed-in admin. It is served with `sandbox; default-src 'none'; img-src data:;
  style-src 'unsafe-inline'` and `nosniff`: shown, never run, even when opened
  directly. `?download=true` makes it an attachment.
- **Previews** run the latest saved files of one workspace. `POST
  /api/v1/artifacts/{id}/preview` (CSRF-checked) creates a random token (only its
  SHA-256 is stored, table `artifact_previews`, migration 0007) valid for an hour,
  and returns `/api/v1/previews/{token}/{path}`. That route needs no session,
  because a sandboxed page sends no cookies; the token is the permission, limited
  to reading that workspace's saved files. Responses carry `sandbox allow-scripts
  allow-modals` (no `allow-same-origin`), `connect-src 'none'`, `form-action
  'none'`, `frame-ancestors 'self'`, `Referrer-Policy: no-referrer` and
  `no-store`. Relative links (`style.css`, `app.js`) resolve inside the same link.
- The app frames previews with `sandbox="allow-scripts allow-modals"`. nginx gives
  `/api/v1/previews/` its own header set, since the app's `frame-ancestors 'none'`
  and `X-Frame-Options: DENY` would block the frame.
- The API mounts the artifact volume read-only; only the worker writes it.

**Consequences**
- A preview can run scripts but cannot read SEED's cookies or storage, reach its
  parent page, or make network requests (checked in Chromium through nginx; see
  progress Increment 13). It can still show anything, including a page that looks
  like a SEED sign-in form; it cannot submit one.
- Previews show the latest files only. Older versions show as source.
- Anyone holding a preview link can read that workspace's saved files for up to
  an hour. Links are not logged in the audit log.
- Expired links are removed when a new one is created.
