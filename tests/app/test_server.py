import hashlib
import json
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import create_app
from app.server_security import EncryptedVault, ServerConfig, password_hash


@pytest.fixture(scope="module")
def config():
    return ServerConfig(
        "owner",
        password_hash("synthetic-long-password"),
        Fernet.generate_key().decode(),
        ["testserver"],
        True,
    )


def test_auth_csrf_session_logout_encrypted_key_restart(tmp_path, config):
    app = create_app(tmp_path, server_config=config, run_worker=False)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/bootstrap").status_code == 401
        assert client.get("/api/saved").status_code == 401
        assert (
            client.get("/history", follow_redirects=False).headers["location"]
            == "/login"
        )
        assert client.get("/healthz").json() == {"ok": True}
        login = client.get("/login")
        assert (
            "Secure" in login.headers["set-cookie"]
            and "HttpOnly" in login.headers["set-cookie"]
        )
        body = {"username": "owner", "password": "synthetic-long-password"}
        assert client.post("/api/login", json=body).status_code == 403
        headers = {"x-csrf-token": app.state.csrf}
        assert (
            client.post(
                "/api/login",
                json=body,
                headers={**headers, "origin": "https://evil.invalid"},
            ).status_code
            == 403
        )
        response = client.post("/api/login", json=body, headers=headers)
        assert (
            response.status_code == 200
            and "SameSite=strict" in response.headers["set-cookie"]
        )
        token = client.cookies["radar_session"]
        assert client.get("/api/bootstrap").json()["server_mode"]
        key = "synthetic-youtube-key-for-test"
        assert (
            client.put(
                "/api/credential", json={"api_key": key}, headers=headers
            ).status_code
            == 200
        )
        assert key.encode() not in (tmp_path / "youtube-key.enc").read_bytes()
        assert key not in client.get("/api/bootstrap").text
        assert token.encode() not in (tmp_path / "radar.sqlite").read_bytes()
        assert client.post("/api/logout", headers=headers).status_code == 200
        client.cookies.set("radar_session", token)
        assert client.get("/api/bootstrap").status_code == 401
    with TestClient(
        create_app(tmp_path, server_config=config, run_worker=False),
        base_url="https://testserver",
    ) as client:
        assert client.get("/api/bootstrap").status_code == 401
    assert EncryptedVault(tmp_path, config.encryption_key).get() == key


def test_rate_limit_expired_session_and_bad_host(tmp_path, config):
    app = create_app(tmp_path, server_config=config, run_worker=False)
    with TestClient(app, base_url="https://testserver") as client:
        client.get("/login")
        headers = {"x-csrf-token": app.state.csrf}
        for _ in range(5):
            assert (
                client.post(
                    "/api/login",
                    headers=headers,
                    json={"username": "owner", "password": "wrong"},
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/login",
                headers=headers,
                json={"username": "owner", "password": "wrong"},
            ).status_code
            == 429
        )
        with app.state.store.connect() as conn:
            conn.execute(
                "INSERT INTO app_sessions VALUES (?,?,?)",
                (hashlib.sha256(b"expired").hexdigest(), time.time() - 1, "version"),
            )
        client.cookies.set("radar_session", "expired")
        assert client.get("/api/bootstrap").status_code == 401
        assert (
            client.get("/healthz", headers={"host": "evil.invalid"}).status_code == 400
        )


def test_server_config_fails_closed_and_corrupt_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_MODE", "server")
    monkeypatch.delenv("RADAR_SERVER_CONFIG_FILE", raising=False)
    with pytest.raises(RuntimeError):
        ServerConfig.from_env()
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"username": "owner"}))
    monkeypatch.setenv("RADAR_SERVER_CONFIG_FILE", str(path))
    with pytest.raises(RuntimeError):
        ServerConfig.from_env()
    vault = EncryptedVault(tmp_path, Fernet.generate_key().decode())
    vault.save("synthetic-key")
    other = EncryptedVault(tmp_path, Fernet.generate_key().decode())
    assert not other.status()["configured"] and other.status()["error"]
