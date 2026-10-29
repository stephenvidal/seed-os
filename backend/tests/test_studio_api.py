"""Studio API (ADR-0015): listing saved files, their versions and content, and
sandboxed previews served through short-lived links."""

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from seed_api.config import Settings
from seed_api.studio.api import CONTENT_CSP, PREVIEW_CSP

from .conftest import sign_in, start

CONV = uuid.UUID("00000000-0000-4000-8000-000000000001")
LONE = uuid.UUID("00000000-0000-4000-8000-000000000002")
OTHER = uuid.UUID("00000000-0000-4000-8000-000000000003")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


@pytest.fixture
def api(db_settings: Settings, root: Path) -> Iterator[TestClient]:
    with start(db_settings.model_copy(update={"artifact_root": str(root)})) as c:
        yield sign_in(c)


class Seed:
    """Writes artifacts the way the worker does: content under its hash, rows in Postgres."""

    def __init__(self, db_url: str, root: Path) -> None:
        self.db_url, self.root = db_url, root

    def blob(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.root / "blobs" / sha[:2] / sha
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return sha

    def file(
        self, workspace: uuid.UUID, path: str, *contents: bytes | None, conv: uuid.UUID | None
    ) -> uuid.UUID:
        aid = uuid.uuid4()
        with psycopg.connect(self.db_url) as conn:
            conn.execute(
                "INSERT INTO artifacts (id, workspace_id, conversation_id, path) "
                "VALUES (%s, %s, %s, %s)",
                (aid, workspace, conv, path),
            )
            for n, data in enumerate(contents, start=1):
                conn.execute(
                    "INSERT INTO artifact_versions (artifact_id, version, sha256, size) "
                    "VALUES (%s, %s, %s, %s)",
                    (
                        aid,
                        n,
                        None if data is None else self.blob(data),
                        None if data is None else len(data),
                    ),
                )
            conn.execute(
                "UPDATE artifacts SET updated_at = clock_timestamp() WHERE id = %s", (aid,)
            )
        return aid


@pytest.fixture
def seed(api: TestClient, db_url: str, root: Path) -> Seed:
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO conversations (id, owner, title, model) VALUES (%s, 'admin', 'Site', 'm')",
            (CONV,),
        )
        conn.execute(
            "INSERT INTO tasks (id, created_by, title, model, prompt, state, max_attempts) "
            "VALUES (%s, 'admin', 'Lone job', 'm', 'p', 'completed', 3)",
            (LONE,),
        )
    return Seed(db_url, root)


def test_studio_needs_a_signed_in_admin(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/artifacts").status_code == 401


def test_list_and_detail(api: TestClient, seed: Seed) -> None:
    page = seed.file(CONV, "site/index.html", b"<h1>v1</h1>", b"<h1>v2</h1>", conv=CONV)
    seed.file(CONV, "site/style.css", b"h1{color:red}", conv=CONV)
    gone = seed.file(LONE, "notes.txt", b"n", None, conv=None)

    rows = api.get("/api/v1/artifacts").json()
    assert [(r["path"], r["versions"], r["latest"]["deleted"]) for r in rows] == [
        ("notes.txt", 2, True),  # most recently changed first
        ("site/style.css", 1, False),
        ("site/index.html", 2, False),
    ]
    lone, css, html = rows
    assert lone["task_id"] == str(LONE) and lone["conversation_id"] is None
    assert lone["source_title"] == "Lone job"
    assert lone["latest"]["size"] is None
    assert html["source_title"] == "Site" and html["task_id"] is None
    assert html["media_type"] == "text/html; charset=utf-8"
    assert css["media_type"] == "text/css; charset=utf-8"
    assert html["latest"]["version"] == 2 and html["latest"]["size"] == len(b"<h1>v2</h1>")

    only = api.get("/api/v1/artifacts", params={"conversation_id": str(CONV)}).json()
    assert [r["path"] for r in only] == ["site/style.css", "site/index.html"]

    detail = api.get(f"/api/v1/artifacts/{page}").json()
    assert detail["artifact"]["path"] == "site/index.html"
    assert [(v["version"], v["deleted"]) for v in detail["versions"]] == [(2, False), (1, False)]
    assert api.get(f"/api/v1/artifacts/{gone}").json()["versions"][0]["deleted"] is True
    assert api.get(f"/api/v1/artifacts/{uuid.uuid4()}").status_code == 404


def test_content_is_shown_but_never_run(api: TestClient, seed: Seed) -> None:
    page = seed.file(CONV, "site/index.html", b"<script>x</script>", b"<h1>v2</h1>", conv=CONV)
    gone = seed.file(LONE, "notes.txt", b"n", None, conv=None)

    r = api.get(f"/api/v1/artifacts/{page}/versions/1/content")
    assert r.status_code == 200 and r.content == b"<script>x</script>"
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["content-security-policy"] == CONTENT_CSP
    assert CONTENT_CSP.startswith("sandbox;") and "script-src" not in CONTENT_CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == "inline; filename*=UTF-8''index.html"
    assert api.get(f"/api/v1/artifacts/{page}/versions/2/content").content == b"<h1>v2</h1>"

    d = api.get(f"/api/v1/artifacts/{page}/versions/2/content", params={"download": "true"})
    assert d.headers["content-disposition"] == "attachment; filename*=UTF-8''index.html"

    assert api.get(f"/api/v1/artifacts/{page}/versions/3/content").status_code == 404
    r = api.get(f"/api/v1/artifacts/{gone}/versions/2/content")
    assert r.status_code == 410 and r.json()["error"]["code"] == "deleted"
    assert api.get(f"/api/v1/artifacts/{gone}/versions/1/content").content == b"n"


def test_content_needs_the_artifact_root(db_settings: Settings, db_url: str, root: Path) -> None:
    with start(db_settings) as c:  # no SEED_ARTIFACT_ROOT
        sign_in(c)
        aid = Seed(db_url, root).file(LONE, "a.txt", b"a", conv=None)
        assert c.get("/api/v1/artifacts").status_code == 200  # listing still works
        r = c.get(f"/api/v1/artifacts/{aid}/versions/1/content")
        assert r.status_code == 503 and r.json()["error"]["code"] == "artifacts_not_configured"


def test_preview_links_serve_one_workspace_sandboxed(
    api: TestClient, seed: Seed, db_url: str
) -> None:
    page = seed.file(CONV, "site/index.html", b"<h1>old</h1>", b"<link href=style.css>", conv=CONV)
    seed.file(CONV, "site/style.css", b"h1{}", conv=CONV)
    seed.file(OTHER, "secret.txt", b"other workspace", conv=None)
    gone = seed.file(LONE, "notes.txt", b"n", None, conv=None)

    csrf = api.headers.pop("X-CSRF-Token")
    assert api.post(f"/api/v1/artifacts/{page}/preview").status_code == 403
    api.headers["X-CSRF-Token"] = csrf
    r = api.post(f"/api/v1/artifacts/{page}/preview")
    assert r.status_code == 201
    url = r.json()["url"]
    assert url.startswith("/api/v1/previews/") and url.endswith("/site/index.html")
    assert r.json()["expires_in"] == 3600
    token = url.split("/")[4]

    anon = TestClient(api.app)  # the sandboxed frame sends no cookies
    r = anon.get(url)
    assert r.status_code == 200 and r.content == b"<link href=style.css>"  # latest version
    assert r.headers["content-security-policy"] == PREVIEW_CSP
    assert "connect-src 'none'" in PREVIEW_CSP and "allow-same-origin" not in PREVIEW_CSP
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    css = anon.get(f"/api/v1/previews/{token}/site/style.css")
    assert css.content == b"h1{}" and css.headers["content-type"] == "text/css; charset=utf-8"

    assert anon.get(f"/api/v1/previews/{token}/secret.txt").status_code == 404
    assert anon.get(f"/api/v1/previews/{token}/../secret.txt").status_code == 404
    assert anon.get(f"/api/v1/previews/{'x' * 43}/site/index.html").status_code == 404
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE artifact_previews SET expires_at = now() - interval '1 second'")
    assert anon.get(url).status_code == 404  # expired
    with psycopg.connect(db_url) as conn:
        stored = conn.execute("SELECT token_hash FROM artifact_previews").fetchone()
    assert stored == (hashlib.sha256(token.encode()).hexdigest(),)  # never the token itself

    r = api.post(f"/api/v1/artifacts/{gone}/preview")
    assert r.status_code == 410
