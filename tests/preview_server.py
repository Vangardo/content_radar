"""Isolated server-mode UI fixture. Credentials are synthetic, never production."""

import sys
import tempfile
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet

from app.main import create_app
from app.server_security import ServerConfig, password_hash
from tests.app_support import MetadataPages, engine_with

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="radar-auth-qa-") as folder:
        config = ServerConfig(
            "fixture-owner",
            password_hash("fixture-password-123"),
            Fernet.generate_key().decode(),
            ["127.0.0.1", "localhost"],
            False,
        )
        app = create_app(
            Path(folder),
            engine_type=engine_with(MetadataPages()),
            server_config=config,
            test_mode=True,
        )
        if "--catalog" in sys.argv:
            from tests.catalog_fixture import seed_catalog

            app.state.store.initialize()
            app.state.store.keys.initialize()
            app.state.store.keys.save(
                "Тестовый ключ", "fixture", "synthetic-fixture-youtube-key", "default"
            )
            seed_catalog(app.state.store)
        uvicorn.run(app, host="127.0.0.1", port=8879, access_log=False)
