from __future__ import annotations

import hashlib

import keyring


class SecretStore:
    """OS credential vault only; never use a file/plaintext fallback."""

    def __init__(self, instance: str):
        self.service = (
            "YouTubeTopicRadar." + hashlib.sha256(instance.encode()).hexdigest()[:16]
        )
        self.username = "youtube-api-key"

    def backend(self):
        backend = keyring.get_keyring()
        module = type(backend).__module__
        if not any(
            part in module
            for part in ("Windows", "macOS", "SecretService", "libsecret")
        ):
            raise RuntimeError(
                "Системное хранилище ключей недоступно. Настройте Windows Credential Manager или системный keyring."
            )
        return backend

    def get(self):
        return self.backend().get_password(self.service, self.username)

    def named(self, ident):
        if ident == "default":
            return self
        vault = object.__new__(SecretStore)
        vault.service, vault.username = self.service, "youtube-api-key:" + ident
        return vault

    def save(self, key):
        self.backend().set_password(self.service, self.username, key)

    def delete(self):
        backend = self.backend()
        if backend.get_password(self.service, self.username):
            backend.delete_password(self.service, self.username)

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
                "error": "Не удалось открыть системное хранилище ключей.",
            }
