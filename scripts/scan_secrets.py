"""Download a fixed Gitleaks release, verify SHA256, scan with full redaction."""

import hashlib
import io
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "8.30.1"
BASE = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/"
ARCHIVE = f"gitleaks_{VERSION}_linux_x64.tar.gz"


def download(name):
    request = urllib.request.Request(
        BASE + name, headers={"User-Agent": "Topic-Radar-CI"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    archive = download(ARCHIVE)
    checksums = download(f"gitleaks_{VERSION}_checksums.txt").decode()
    expected = next(
        line.split()[0]
        for line in checksums.splitlines()
        if line.split()[-1] == ARCHIVE
    )
    if hashlib.sha256(archive).hexdigest() != expected:
        raise RuntimeError("Gitleaks download checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="radar-gitleaks-") as folder:
        binary = Path(folder) / "gitleaks"
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            binary.write_bytes(tar.extractfile("gitleaks").read())
        binary.chmod(0o700)
        subprocess.run(
            [str(binary), "git", ".", "--redact", "--no-banner", "--log-opts=--all"],
            check=True,
        )


if __name__ == "__main__":
    main()
