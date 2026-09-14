# Changelog

## 2026.09.2

- The anonymous vocabulary endpoint (`GET /agent/vocab/`) and the CLI `vocab`
  command were removed. The fmt-* builders keep validating against the
  built-in vocabulary snapshot (offline, unchanged); when the server rejects
  a value anyway, its error message lists the accepted options.

## 2026.09.1

- Network commands in the full CLI build now ride the MCP endpoint
  (`POST /mcp/`, stateless JSON-RPC — 2026-07-28 MCP spec) instead of the
  REST tool mirror; the mirror endpoints were removed. `tools` lists the
  live catalog via `tools/list`; every tool command maps to `tools/call`.
- File upload keeps its dedicated multipart REST endpoint (`upload`), and
  login/switch (`/auth/agent/*`) and the anonymous vocabulary endpoint are
  unchanged.
- Server: agent credential validation is now Redis-cached (cache-aside with
  push invalidation on reset/membership end/ownership transfer); the MCP
  server runs stateless (`WithStateLess`) on mcp-go v1.0.0.
- Platform connectors (e.g. Doubao) authorize via the new OAuth endpoints
  (authorization code + PKCE, dynamic client registration, RFC 8414
  metadata) and receive the same long-lived PAT as the CLI.

## 2026.09.0

First packaged release of the mapview skill. Language axis (zh canonical,
en mirror) and distribution profiles (direct / connector) ship together;
all entries below are `both` builds unless marked.

- `zh:` SKILL.md rewritten as the Chinese canonical source: build-conditional
  connection flow (full-build guided login vs lite-build MCP connector),
  Chinese-only replies, single-language welcome/quota templates, description
  compressed and neutralized for platform review.
- `en:` SKILL.en.md added as the hand-maintained English mirror (display-name
  `MapView`); replies follow the user's language, defaulting to English.
- CLI: commands regrouped into semantic sections (account / network / local /
  restfile); `status` reports the build variant; the fmt-* commands validate
  against the built-in vocabulary snapshot (no implicit server fetch — the
  explicit `vocab` command still fetches the live lists).
- `full` CLI behavior change: fmt-* no longer fetch `/agent/vocab`
  implicitly; validation uses the embedded snapshot.
- `lite` CLI source added (`mapview_cli_lite.py`): local-deterministic
  commands only, cropped commands print an MCP redirect; network code,
  token store, and host are physically absent.
- `lite` SKILL doc: the connector package carries its own SKILL.md
  (`SKILL.lite.md`) — description and body describe the local-only CLI
  surface plus the MCP channel, never the full build's login/direct-API
  flow.
- `references/` directory renamed from `reference/`; repo directory renamed
  `docs/mcp/` → `skills/mapview/`.
- Packaging: deterministic zips per (sources, host) with the deployment host
  baked into the full CLI's `DEFAULT_HOST`; served via the admin-authenticated
  download endpoint (`GET /admin/skill/:filename/`).
