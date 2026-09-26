import json
import sqlite3
import threading
import time
import uuid

import pytest
import requests
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.access import AccessTokens
from app.credentials import KeyRegistry
from app.main import create_app
from app.models import ScanConfig
from app.monitoring import Scheduler
from app.server_security import EncryptedVault, ServerConfig, password_hash
from app.storage import ROOT, Store
from tests.app_support import MemoryVault, Pages, engine_with


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda *a, **k: pytest.fail("Live network forbidden"),
    )


@pytest.fixture
def setup(tmp_path):
    vault = MemoryVault()
    vault.save("synthetic-default-youtube-key")
    transport = Pages()
    app = create_app(tmp_path, vault, engine_with(transport), run_worker=False)
    with TestClient(app) as client:
        client.get("/")
        yield app, client, {"X-CSRF-Token": app.state.csrf}, transport


def execute(app, transport):
    store = app.state.store
    ident = store.claim()
    assert ident
    if store.run(ident)["kind"] == "refilter":
        store.refilter(ident)
    else:
        engine_with(transport)(
            store,
            ident,
            store.keys.get(store.run(ident)["config"]["credential_id"]),
            threading.Event(),
        ).execute()
    return ident


def new(client, headers, **extra):
    body = {
        "config": {"seeds": ["query"], "language": "ru"},
        "request_id": uuid.uuid4().hex,
        **extra,
    }
    r = client.post("/api/research", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_multiple_research_queue_monitor_and_once_are_distinct(setup):
    app, c, h, t = setup
    a = new(c, h, monitor=True)
    b = new(c, h, monitor=False)
    assert a != b
    assert execute(app, t) == a and execute(app, t) == b
    rows = {r["id"]: r for r in c.get("/api/research").json()["research"]}
    assert rows[a]["is_monitor"] and rows[a]["schedule"]["enabled"]
    assert not rows[b]["is_monitor"]
    assert rows[a]["schedule"]["next_full"] > time.time() + 3 * 3600
    assert rows[a]["small_videos"] == 2
    assert rows[a]["last_observed_at"]
    paused = c.put(
        f"/api/research/{a}/schedule", headers=h, json={"enabled": False}
    ).json()
    assert not paused["enabled"]
    assert c.get("/api/research").json()["research"][0]["is_monitor"] is False


def test_defaults_short_windows_depth500_and_config_apply(setup):
    app, c, h, t = setup
    ident = new(c, h, config={"seeds": ["query"], "days": 1, "max_results": 500})
    execute(app, t)
    search = [p for e, p in t.params if e == "search"]
    import datetime as dt

    seconds = (
        dt.datetime.fromisoformat(search[0]["publishedBefore"].replace("Z", "+00:00"))
        - dt.datetime.fromisoformat(search[0]["publishedAfter"].replace("Z", "+00:00"))
    ).total_seconds()
    assert 86399 <= seconds <= 86401
    assert all(p["maxResults"] == 50 for p in search)
    before = len(t.calls)
    r = c.put(
        f"/api/research/{ident}/config",
        headers=h,
        json={
            "name": "Renamed",
            "seeds": ["query"],
            "days": 2,
            "max_results": 200,
            "excluded_categories": ["10"],
        },
    )
    assert r.status_code == 200
    execute(app, t)
    assert len(t.calls) == before
    assert app.state.store.collection_runs(ident)[0]["config"]["days"] == 2
    assert c.get("/api/categories").json()["10"] == "Музыка"


def test_keys_project_accounting_soft_estimate_and_real_quota_block(setup):
    app, c, h, t = setup
    s = app.state.store
    a = c.post(
        "/api/keys",
        headers=h,
        json={
            "name": "Project A",
            "project_id": "project-a",
            "api_key": "synthetic-project-a-key",
        },
    ).json()["id"]
    b = c.post(
        "/api/keys",
        headers=h,
        json={
            "name": "Second A",
            "project_id": "project-a",
            "api_key": "synthetic-second-a-key",
        },
    ).json()["id"]
    s.keys.charge(a, "search", 1)
    s.keys.charge(b, "search", 1)
    listing = c.get("/api/keys").json()
    assert next(x for x in listing if x["id"] == a)["project_search_used"] == 2
    assert "synthetic-project-a-key" not in json.dumps(listing)
    s.set_setting("budget", {"search_limit": 0, "unit_limit": 0})
    ident = new(c, h, config={"seeds": ["query"], "credential_id": a})
    execute(app, t)
    assert s.run(ident)["status"] == "completed"  # estimate isn't a hard block
    t.fail_page = 0
    failed = c.post(
        f"/api/research/{ident}/actions", headers=h, json={"kind": "repeat"}
    ).json()["id"]
    execute(app, t)
    assert s.run(failed)["status"] == "waiting_quota"
    assert s.keys.blocked(a, "search") and s.keys.blocked(b, "search")
    assert not s.keys.blocked("default", "search") and not s.keys.blocked(a, "videos")
    before = len(t.calls)
    refresh = c.post(
        f"/api/research/{ident}/actions", headers=h, json={"kind": "refresh"}
    ).json()["id"]
    execute(app, t)
    assert s.run(refresh)["status"] == "completed" and t.calls[before:] == ["videos"]
    s.keys.rename_project(a, "Renamed", "fixed-project-a")
    assert s.keys.blocked(a, "search")  # renaming cannot erase an exhaustion response
    assert c.delete("/api/keys/" + a, headers=h).status_code == 200
    assert not s.keys.available(a)
    assert c.post("/api/keys/" + a + "/enable", headers=h).status_code == 200
    assert s.keys.available(a)


def test_one_available_key_is_automatically_used(setup):
    app, c, h, t = setup
    ident = c.post(
        "/api/keys",
        headers=h,
        json={
            "name": "Only",
            "project_id": "only-project",
            "api_key": "synthetic-only-project-key",
        },
    ).json()["id"]
    c.delete("/api/keys/default", headers=h)
    run = new(c, h)
    assert app.state.store.run(run)["config"]["credential_id"] == ident
    assert (
        c.post(
            "/api/keys",
            headers=h,
            json={
                "name": "Duplicate",
                "project_id": "other",
                "api_key": "synthetic-only-project-key",
            },
        ).status_code
        == 400
    )


def test_chart_actual_deltas_no_fabricated_growth_and_channel_grouping(
    setup, monkeypatch
):
    app, c, h, t = setup
    s = app.state.store
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    ident = new(c, h)
    execute(app, t)
    assert all(
        not x["points"] for x in c.get(f"/api/research/{ident}/chart").json()["series"]
    )
    clock[0] += 3600
    t.views += 2000
    c.post(f"/api/research/{ident}/actions", headers=h, json={"kind": "refresh"})
    execute(app, t)
    for kind in ["videos", "channels", "topics"]:
        chart = c.get(f"/api/research/{ident}/chart?kind={kind}").json()
        assert chart["series"] and chart["series"][0]["points"][0][
            "value"
        ] == pytest.approx(2000)
    clock[0] += 3600
    t.views -= 100
    c.post(f"/api/research/{ident}/actions", headers=h, json={"kind": "refresh"})
    execute(app, t)
    assert len(c.get(f"/api/research/{ident}/chart").json()["series"][0]["points"]) == 1
    assert not any(
        s["points"]
        for s in c.get(f"/api/research/{ident}/chart?run_id={ident}").json()["series"]
    )
    assert c.get(f"/api/research/{ident}/chart?run_id=foreign").status_code == 404


@pytest.fixture(scope="module")
def auth_config():
    return ServerConfig(
        "admin",
        password_hash("synthetic-product-password"),
        Fernet.generate_key().decode(),
        ["testserver"],
        True,
    )


def test_personal_api_token_scopes_expiration_revocation_owner_and_secret_hiding(
    tmp_path, auth_config
):
    vault = MemoryVault()
    vault.save("synthetic-default-youtube-key")
    app = create_app(tmp_path, vault, run_worker=False, server_config=auth_config)
    with TestClient(app, base_url="https://testserver") as c:
        c.get("/login")
        h = {"X-CSRF-Token": app.state.csrf}
        assert (
            c.post(
                "/api/login",
                headers=h,
                json={"username": "admin", "password": "synthetic-product-password"},
            ).status_code
            == 200
        )
        read = c.post(
            "/api/access-tokens", headers=h, json={"name": "Reader", "scope": "read"}
        ).json()
        write = c.post(
            "/api/access-tokens", headers=h, json={"name": "Writer", "scope": "write"}
        ).json()
        assert read["token"] not in c.get("/api/access-tokens").text
        assert write["token"].encode() not in (tmp_path / "radar.sqlite").read_bytes()
        s = app.state.store
        with s.connect() as conn:
            conn.execute(
                "INSERT INTO app_users VALUES ('other','other','user',NULL,?,0)",
                (time.time(),),
            )
        other = AccessTokens(s).create("Other", "write", owner="other")
        c.post("/api/logout", headers=h)
        c.cookies.clear()
        rh = {"Authorization": "Bearer " + read["token"]}
        wh = {"Authorization": "Bearer " + write["token"]}
        assert c.get("/api/v1/me").status_code == 401
        assert c.get("/api/v1/me", headers=rh).json()["owner_id"] == "admin"
        assert (
            c.post(
                "/api/v1/research", headers=rh, json={"config": {"seeds": ["query"]}}
            ).status_code
            == 403
        )
        body = {"config": {"seeds": ["query"]}, "request_id": "external-unique-123"}
        created = c.post("/api/v1/research", headers=wh, json=body)
        assert created.status_code == 200, created.text
        ident = created.json()["id"]
        assert c.post("/api/v1/research", headers=wh, json=body).json()["id"] == ident
        data = c.get("/api/v1/research/" + ident, headers=rh)
        assert (
            data.status_code == 200 and "synthetic-default-youtube-key" not in data.text
        )
        assert c.get("/api/keys", headers=wh).status_code == 401
        public_keys = c.get("/api/v1/credentials", headers=rh)
        assert public_keys.status_code == 200
        assert public_keys.json()[0]["id"] == "default"
        assert "synthetic-default-youtube-key" not in public_keys.text
        oh = {"Authorization": "Bearer " + other["token"]}
        assert not c.get("/api/v1/research", headers=oh).json()["research"]
        assert c.get("/api/v1/research/" + ident, headers=oh).status_code == 404
        assert c.post("/api/v1/research", headers=oh, json=body).status_code == 400
        assert c.get("/api/v1/openapi.json", headers=rh).status_code == 200
        assert (
            c.post(
                "/api/v1/research", headers={**wh, "Content-Length": "70000"}, json=body
            ).status_code
            == 413
        )
        AccessTokens(s).revoke(write["id"])
        assert c.get("/api/v1/me", headers=wh).status_code == 401
        with s.connect() as conn:
            conn.execute(
                "UPDATE app_access_tokens SET expires_at=0 WHERE id=?", (read["id"],)
            )
        assert c.get("/api/v1/me", headers=rh).status_code == 401


def test_encrypted_multiple_key_slots_are_distinct_and_restart(tmp_path):
    key = Fernet.generate_key().decode()
    vault = EncryptedVault(tmp_path, key)
    vault.save("synthetic-default-key")
    vault.named("second").save("synthetic-second-key")
    fresh = EncryptedVault(tmp_path, key)
    assert (
        fresh.get() == "synthetic-default-key"
        and fresh.named("second").get() == "synthetic-second-key"
    )
    assert all(b"synthetic" not in p.read_bytes() for p in tmp_path.glob("*.enc"))


def test_local_admin_setup_preserves_os_vault_and_requires_login(tmp_path, monkeypatch):
    from app.local_setup import setup as local_setup

    password = local_setup(tmp_path)
    assert password not in (tmp_path / "local-auth.json").read_text()
    with pytest.raises(RuntimeError):
        local_setup(tmp_path)
    vault = MemoryVault()
    vault.save("synthetic-existing-os-key")
    monkeypatch.setattr("app.main.SecretStore", lambda _: vault)
    app = create_app(tmp_path, run_worker=False)
    assert app.state.vault is vault
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/bootstrap").status_code == 401
        c.get("/login")
        assert (
            c.post(
                "/api/login",
                headers={"X-CSRF-Token": app.state.csrf},
                json={"username": "admin", "password": password},
            ).status_code
            == 200
        )
        assert c.get("/api/bootstrap").json()["credential"]["configured"]


def test_v3_migration_preserves_original_rows_and_assigns_admin(tmp_path):
    p = tmp_path / "radar.sqlite"
    c = sqlite3.connect(p)
    for migration in ["001_initial.sql", "002_collections.sql", "003_monitoring.sql"]:
        c.executescript((ROOT / "migrations" / migration).read_text(encoding="utf-8"))
    cfg = json.dumps(ScanConfig(seeds=["query"]).model_dump())
    c.execute(
        "INSERT INTO app_runs(id,request_id,kind,status,config_json,engine_sha,created_at,collection_id) VALUES ('legacy','legacy','discover','completed',?,'sha',?,'legacy')",
        (cfg, time.time()),
    )
    c.execute("INSERT INTO quota VALUES ('2026-09-24',8,3)")
    c.commit()
    original = c.execute("SELECT * FROM app_runs").fetchall()
    c.close()
    s = Store(p)
    s.initialize()
    s.initialize()
    with s.connect() as c:
        assert [tuple(r) for r in c.execute("SELECT * FROM app_runs")] == original
        assert tuple(
            c.execute("SELECT id,owner_id,credential_id FROM app_research").fetchone()
        ) == ("legacy", "admin", "default")
        assert tuple(
            c.execute("SELECT key_id,search_calls,units FROM app_key_usage").fetchone()
        ) == ("default", 3, 8)
