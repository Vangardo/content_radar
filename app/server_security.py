"""Single-owner server mode. Local mode continues to use the OS vault."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=2**17,
        r=8,
        p=1,
        maxmem=256 * 1024**2,
    ).hex()
    return f"scrypt:{salt}:{digest}"


@dataclass
class ServerConfig:
    username: str
    password_hash: str
    encryption_key: str
    hosts: list[str]
    secure_cookies: bool = True

    @classmethod
    def from_env(cls, local_path=None):
        mode = os.environ.get("RADAR_MODE", "local")
        if mode == "local":
            if not local_path or not local_path.exists():
                return None
        if mode not in {"local", "server"}:
            raise RuntimeError("RADAR_MODE должен быть local или server")
        path = (
            os.environ.get("RADAR_SERVER_CONFIG_FILE")
            if mode == "server"
            else str(local_path)
        )
        if not path:
            raise RuntimeError(
                "Сначала создайте серверные секреты: python -m app.server_setup"
            )
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            config = cls(**data)
            kind, salt, digest = config.password_hash.split(":")
            if (
                kind != "scrypt"
                or len(bytes.fromhex(salt)) != 16
                or len(bytes.fromhex(digest)) != 64
            ):
                raise ValueError()
            from cryptography.fernet import Fernet

            Fernet(config.encryption_key.encode())
            if not config.username or not config.hosts or "*" in config.hosts:
                raise ValueError()
            return config
        except Exception:
            raise RuntimeError("Некорректная конфигурация серверных секретов") from None


class EncryptedVault:
    def __init__(self, directory, key):
        from cryptography.fernet import Fernet

        self.path = directory / "youtube-key.enc"
        self.fernet = Fernet(key.encode())

    def get(self):
        return (
            self.fernet.decrypt(self.path.read_bytes()).decode()
            if self.path.exists()
            else None
        )

    def named(self, ident):
        if ident == "default":
            return self
        vault = object.__new__(EncryptedVault)
        vault.fernet = self.fernet
        vault.path = self.path.with_name("youtube-key-" + ident + ".enc")
        return vault

    def save(self, key):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("wb") as file:
            os.chmod(temporary, 0o600)
            file.write(self.fernet.encrypt(key.encode()))
        temporary.replace(self.path)

    def delete(self):
        self.path.unlink(missing_ok=True)

    def status(self):
        try:
            key = self.get()
            return {
                "configured": bool(key),
                "fingerprint": hashlib.sha256(key.encode()).hexdigest()[:10]
                if key
                else None,
                "error": None,
            }
        except Exception:
            return {
                "configured": False,
                "fingerprint": None,
                "error": "Не удалось расшифровать ключ. Проверьте серверный секрет.",
            }


class ServerAuth:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.cookie = "radar_session"
        # Changing either credential revokes all existing sessions.
        self.version = hashlib.sha256(
            (config.username + config.password_hash).encode()
        ).hexdigest()

    def valid(self, token):
        if not token or len(token) > 200:
            return False
        with self.store.connect() as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM app_sessions WHERE token_hash=? AND expires_at>? AND credential_version=? AND EXISTS (SELECT 1 FROM app_users WHERE id='admin' AND disabled=0)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        time.time(),
                        self.version,
                    ),
                ).fetchone()
            )

    def login(self, username, password):
        now = time.time()
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM app_login_attempts WHERE attempted_at<?", (now - 300,)
            )
            if (
                conn.execute("SELECT COUNT(*) FROM app_login_attempts").fetchone()[0]
                >= 5
            ):
                return None, 429
            conn.execute("INSERT INTO app_login_attempts VALUES (?)", (now,))
        expected = self.config.password_hash
        correct = secrets.compare_digest(
            password_hash(password, expected.split(":")[1]), expected
        )
        if not correct or not secrets.compare_digest(
            username.encode(), self.config.username.encode()
        ):
            return None, 401
        token = secrets.token_urlsafe(32)
        with self.store.connect() as conn:
            conn.execute("DELETE FROM app_sessions WHERE expires_at<?", (now,))
            conn.execute("DELETE FROM app_login_attempts")
            conn.execute(
                "INSERT INTO app_sessions VALUES (?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), now + 43200, self.version),
            )
        return token, 200

    def logout(self, token):
        with self.store.connect() as conn:
            conn.execute(
                "DELETE FROM app_sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
