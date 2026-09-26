"""Isolated manual browser acceptance server: python -m tests.preview_fixture.

Synthetic API transport and memory-only credential, separate temporary database.
Never use this server for actual research or enter a real API key into it.
"""

import tempfile
from pathlib import Path

import uvicorn

from app.main import create_app
from tests.app_support import Pages, MemoryVault, engine_with


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="radar-browser-qa-") as folder:
        app = create_app(
            Path(folder), MemoryVault(), engine_with(Pages()), test_mode=True
        )
        uvicorn.run(app, host="127.0.0.1", port=8878, access_log=False)
