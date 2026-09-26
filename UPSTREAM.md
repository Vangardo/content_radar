# Upstream provenance

- Repository: https://github.com/sentien-labs/youtube-niche
- Snapshot: d8f605c273e15cbdcb536ef8e4b076ef892172be
- Downloaded: 2026-09-24, GitHub source ZIP; no fork, push or automatic update.
- Original MIT license: LICENSE. Original README is preserved at docs/UPSTREAM_README.md; its relative links refer to upstream.
- Topic Radar web UI, monitoring, persistence, security and packaging are maintained by Vangardo.

## Local changes to the engine

- Cache: optional get_entry() exposing source timestamp; same kv keys and payloads.
- YouTubeClient: optional endpoint TTLs, request/response hooks, forced refresh,
  Pacific quota day and conservative attempt charging. Default CLI quota behavior
  remains compatible; Radar opts into conservative charging. HTTP errors sanitized. Optional search page_token added for bounded pagination.
- enrich: opt-in preservation of unknown view counts (None).
- winners/topics: opt-in Unicode phrase extraction preserving version tokens;
  original scorer tokenization and defaults remain intact.

The app calls existing transport, batch endpoints, enrichment and keyword fallback.
It does not call analyze_topic(), scoring, model discovery, comments, Trends,
transcripts, autocomplete, forward capture, or upstream report side effects.
Numeric analytics are transparent averages/differences, not opportunity scores.
