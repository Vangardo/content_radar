"""One-time local admin setup. Keeps the existing OS YouTube vault in place."""

import json
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from .server_security import password_hash
from .storage import ROOT


def setup(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "local-auth.json"
    if path.exists():
        raise RuntimeError("Вход уже настроен; существующий пароль не менялся")
    password = secrets.token_urlsafe(18)
    config = {
        "username": "admin",
        "password_hash": password_hash(password),
        "encryption_key": Fernet.generate_key().decode(),
        "hosts": ["127.0.0.1", "localhost"],
        "secure_cookies": False,
    }
    with path.open("x", encoding="utf-8") as f:
        os.chmod(path, 0o600)
        json.dump(config, f)
    return password


if __name__ == "__main__":
    password = setup(Path(os.environ.get("RADAR_DATA_DIR", ROOT / "data")))
    print("Логин: admin\nОдноразовый показ пароля: " + password)
    print("После перезапуска вход защищён. Сохраните пароль в менеджере паролей.")
