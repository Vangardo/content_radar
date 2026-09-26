"""Fail closed on private files and inconsistent public release metadata."""

import re
import subprocess
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = (
    subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
)
for name in filter(None, files):
    path = Path(name)
    assert not path.is_absolute() and ".." not in path.parts, "Invalid tracked path"
    assert not name.startswith(
        ("data/", "artifacts/", "backups/", "deploy/secrets/", "deploy/dev/")
    ), name
    assert path.suffix.lower() not in {
        ".sqlite",
        ".db",
        ".enc",
        ".pem",
        ".key",
        ".pfx",
    }, name
    assert path.name not in {
        "server.json",
        "local-auth.json",
        "token.json",
        "README_DEV.md",
        "AGENTS.md",
    }, name
    assert not (path.name.startswith(".env") and path.name != ".env.example"), name
version = (root / "VERSION").read_text().strip()
assert re.fullmatch(r"\d+\.\d+\.\d+", version), "Invalid release version"
meta = tomllib.loads((root / "pyproject.toml").read_text())
assert meta["project"]["version"] == version, "Version mismatch"
assert meta["project"]["name"] == "content-radar"
assert f"content_radar:{version}" in (root / "compose.release.yaml").read_text()
print("Public file boundaries and release metadata verified")
