"""Start an isolated image with generated credentials; never call YouTube."""

import argparse
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import requests
from cryptography.fernet import Fernet

from app.server_security import password_hash


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    name = "radar-smoke-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="radar-smoke-") as folder:
        password = secrets.token_urlsafe(24)
        config = Path(folder) / "server.json"
        config.write_text(
            json.dumps(
                {
                    "username": "smoke-owner",
                    "password_hash": password_hash(password),
                    "encryption_key": Fernet.generate_key().decode(),
                    "hosts": ["127.0.0.1", "localhost"],
                    "secure_cookies": False,
                }
            ),
            encoding="utf-8",
        )
        os.chmod(config, 0o444)
        started = False
        try:
            docker(
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "--read-only",
                "--tmpfs",
                "/tmp",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--mount",
                "type=volume,dst=/data",
                "--mount",
                f"type=bind,src={config.resolve()},dst=/run/secrets/radar_server,readonly",
                "-p",
                "127.0.0.1::8877",
                args.image,
            )
            started = True
            port = docker("port", name, "8877/tcp").rsplit(":", 1)[1]
            base = "http://127.0.0.1:" + port
            for attempt in range(60):
                try:
                    health = requests.get(base + "/healthz", timeout=2)
                    if health.status_code == 200 and health.json().get("ok") is True:
                        break
                except requests.RequestException:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("Container did not become healthy")
            with requests.Session() as session:
                assert (
                    session.get(base + "/api/bootstrap", timeout=5).status_code == 401
                )
                login = session.get(base + "/login", timeout=5)
                login.raise_for_status()
                csrf = re.search(
                    r'name="csrf-token" content="([^"]+)"', login.text
                ).group(1)
                response = session.post(
                    base + "/api/login",
                    timeout=10,
                    headers={"X-CSRF-Token": csrf},
                    json={"username": "smoke-owner", "password": password},
                )
                response.raise_for_status()
                response = session.get(base + "/api/bootstrap", timeout=5)
                response.raise_for_status()
                assert response.json()["server_mode"] is True
                for path in ("/", "/posts", "/channels", "/history", "/static/app.js"):
                    session.get(base + path, timeout=5).raise_for_status()
                assert not response.json()["credential"]["configured"]
            print(
                "Container verified: health, auth, empty database, static UI, no YouTube key"
            )
        finally:
            if started:
                docker("stop", "--time", "10", name)
            os.chmod(config, 0o600)


if __name__ == "__main__":
    main()
