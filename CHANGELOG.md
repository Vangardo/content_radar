# Changelog

## [0.1.0] — 2026-09-26

First public Topic Radar release. Early single-owner MVP; Russian UI.

### Added

- Keyword research focused on small channels (default: up to 10,000 subscribers).
- Manual scans and recurring monitors with separate discovery and refresh intervals.
- RU/EN search preferences, Shorts/ordinary-video filters and configurable lookback.
- Immutable observations, measured hourly growth and conservative topic grouping.
- Public metadata, descriptions, tags, hashtags, likes and comment counts.
- Channel history; paginated, sortable video/channel/research catalogs.
- Favorites, notes, individual/batch refresh, exports and reversible research deletion.
- Encrypted server key storage, admin login and scoped external HTTP API tokens.
- Docker/HTTPS setup, GHCR package, release archives, CI and contributor documentation.

### Reliability

- Historical refreshes rank IDs before loading metadata, reducing SQLite temporary
  storage pressure. Recoverable storage errors do not terminate the worker.
- Non-JSON server errors display a readable message instead of a JavaScript parse error.

### Known limitations

- API data retained for 28 days; one owner/process per database.
- Shorts detection is a heuristic; search results do not cover all YouTube videos.
- Interrupted operations retain results but do not resume from a checkpoint.
- Linux amd64 container only; UI localization beyond Russian is not included.
- Growth signals are observations, not predictions or profitability scores.

[0.1.0]: https://github.com/Vangardo/content_radar/releases/tag/v0.1.0
