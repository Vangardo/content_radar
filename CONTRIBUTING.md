# Contributing to Topic Radar

Reports and pull requests are welcome in Russian or English. Describe a concrete user
problem and a reproducible example with synthetic data. Never attach real API keys,
server configuration, cookies, databases or private exports.

## Development setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24+.
The pinned managed Python includes patched SQLite; system Python may not.

```sh
uv venv --python 3.11.15 .venv
uv pip sync --python .venv requirements-dev.lock
uv run --no-project --python .venv python -X utf8 -m pytest -q
node --test tests/ui_api.test.cjs
```

Windows direct test command:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

Tests use temporary databases and synthetic transports; no live YouTube calls or keys.
Start the fixture UI with `python -m tests.preview_server --catalog` using the virtual
environment. [Demo guide](docs/DEMO.md).

## Conventions

- Python/FastAPI, SQLite, vanilla JavaScript. No runtime LLM dependency.
- Keep lifetime averages distinct from measured growth; unknown data stays unknown.
- Preserve historical snapshots. Add sequential, backward-compatible SQL migrations.
- One worker/process per database. Keep expensive work outside request handlers.
- Reuse the vault, sanitization, CSRF and ownership checks.
- Add regression coverage for logic/API/security bugs; inspect visible UI changes.
- Explain API/schema impact and verification. Avoid unrelated refactoring.

## Checks

```sh
uvx ruff check app tests/app --select E9,F63,F7,F82
node --test tests/ui_api.test.cjs
uvx pip-audit -r requirements-server.lock --no-deps --disable-pip
```

CI runs Python tests on Windows/Linux, JavaScript tests, syntax checks, full-history
secret scanning, dependency auditing and a Docker build/startup check. Lint focuses on
correctness; upstream formatting is preserved.

Locks are generated with uv. Update the relevant .in file and regenerate its .lock
using the supported Python/platform. The server must remain headless and free of
optional upstream LLM/Trends/transcript packages.

## Releases

The supported package is GHCR; Python runs from source (no PyPI release).
Update VERSION, CHANGELOG.md, pyproject.toml, image defaults and quick-start tags together.
Tag the reviewed commit vX.Y.Z and push the tag. Release CI runs before publication,
then publishes the image, source archives, checksums and a GitHub prerelease.
The first release targets Linux amd64. Other architectures require validation.
GitHub's built-in GITHUB_TOKEN handles publication; no personal token is stored.

Review workflow changes carefully. [Private vulnerability reporting](SECURITY.md).
