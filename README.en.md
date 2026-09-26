# Topic Radar

**Find videos gaining traction on small YouTube channels.**

[Русский](README.md) · [Releases](https://github.com/Vangardo/content_radar/releases) · [Container](https://github.com/Vangardo/content_radar/pkgs/container/content_radar)

A self-hosted dashboard with scheduled discovery, measured view growth, channel history,
Shorts filters, favorites and exports. Default focus: channels with up to **10,000 subscribers**.
Russian UI; Russian and English search preferences. No LLM is used by the web application.
Bring your own YouTube Data API key.

![Video catalog with synthetic demonstration data](docs/images/posts.png)

## Quick start: Windows

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git:

```powershell
git clone https://github.com/Vangardo/content_radar.git
cd content_radar
.\setup.ps1
.\.venv\Scripts\python.exe -X utf8 -m app.local_setup
.\start.ps1
```

Open http://127.0.0.1:8877. Local setup prints a generated admin password once.
Store it in your password manager. Add a YouTube API key in Settings and start an investigation.
A patched SQLite runtime is required; the setup script selects one.

For a server, follow the examples in [Docker / HTTPS setup](README_SERVER.md).
The versioned image is `ghcr.io/vangardo/content_radar:0.1.0` for **Linux amd64**.

## Keyless demo

Run `python -X utf8 -m tests.preview_server --catalog` using the virtual environment.
Open http://127.0.0.1:8879 and sign in with `fixture-owner` / `fixture-password-123`.
All data is synthetic and temporary; no YouTube calls are made. Do not enter real keys.

## What it measures

- Broad keyword searches every 4–24 hours, leader refreshes every 30–120 minutes.
- Deduplicated IDs, public metadata, likes and comment counts, channel snapshots.
- Growth requires observations at least 30 minutes apart. Lifetime views/day is separate.
- Small-channel ranking, conservative topic grouping, pagination, sorting and exports.
- Individual refreshes, favorites, reversible research deletion and authenticated HTTP API.

## Scope and security

Early single-owner MVP, not a multi-tenant SaaS. One process per SQLite database.
API data expires after 28 days; notes and saved IDs are separate. Search results are a
sample, not exhaustive coverage. Shorts classification is a heuristic: YouTube Data API
does not expose a definitive `isShort` flag. A signal is not a forecast of your video's success.
Comment text and private channel analytics are not fetched.

Server deployments require HTTPS. Passwords are hashed, API keys encrypted, bearer
tokens revocable. Protect the server secret and backups. [Security policy](SECURITY.md).

## Development and attribution

[Contributing](CONTRIBUTING.md) · [Architecture](docs/ARCHITECTURE.md) · [Changelog](CHANGELOG.md)

Based on [sentien-labs/youtube-niche](https://github.com/sentien-labs/youtube-niche),
under the [MIT license](LICENSE). Upstream CLI code includes optional LLM modules;
Radar does not call them or install their dependencies. See [UPSTREAM.md](UPSTREAM.md).
The supported distribution is source plus Docker, not a PyPI wheel.

Not affiliated with or endorsed by YouTube or Google.
