"""Interactive setup; no password or encryption key is printed."""

import getpass
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet
from .server_security import password_hash


def main():
    path = Path("deploy/secrets/server.json")
    if path.exists():
        raise SystemExit(
            "Файл уже существует. Сохраните его: ключ нужен для расшифровки API-ключа."
        )
    username = input("Логин владельца (Enter: admin): ").strip() or "admin"
    domain = (
        input("Домен сервера (без https://; Enter для localhost): ").strip()
        or "localhost"
    )
    if not username or any(c in domain for c in "/:* "):
        raise SystemExit("Некорректный логин или домен")
    password = getpass.getpass("Пароль (не менее 12 символов): ")
    if len(password) < 12 or password != getpass.getpass("Повторите пароль: "):
        raise SystemExit("Пароли не совпадают или слишком короткий пароль")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = {
        "username": username,
        "password_hash": password_hash(password),
        "encryption_key": Fernet.generate_key().decode(),
        "hosts": list(dict.fromkeys([domain, "localhost", "127.0.0.1"])),
        "secure_cookies": True,
    }
    with path.open("x", encoding="utf-8") as file:
        os.chmod(path, 0o600)
        json.dump(data, file)
    # Compose mounts this file read-only for a non-root UID. The parent directory
    # remains private on the host, so other host users cannot traverse to it.
    os.chmod(path, 0o444)
    print("Создан deploy/secrets/server.json. Сохраните защищённую резервную копию.")


if __name__ == "__main__":
    main()
