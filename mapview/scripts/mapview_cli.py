#!/usr/bin/env python3
"""MapView CLI — build shareable maps from data via the MapView REST API.

A single-file, zero-dependency command-line client for the MapView map-builder
MCP endpoint (/mcp/, JSON-RPC; file upload keeps its multipart /agent/
endpoint and login keeps its REST endpoints). This CLI is the Skill's
default channel; when an MCP client is connected, either channel drives
the same tools.

Setup:
  python3 mapview_cli.py login            # guided: prints a login link, waits, stores the token
  python3 mapview_cli.py login --token "mapview_pat_xxx"   # or store an existing token

Usage:
  python3 mapview_cli.py login            # no args -> browser login flow
  python3 mapview_cli.py switch           # connect to a different workspace via the same flow
  python3 mapview_cli.py login --token mapview_pat_xxx
  python3 mapview_cli.py status
  python3 mapview_cli.py endpoint           # print the MCP endpoint URL (for MCP client config)
  python3 mapview_cli.py create_map --name "My Map" [--desc "..."]
  python3 mapview_cli.py list_maps
  python3 mapview_cli.py get_map --map-id <id>
  python3 mapview_cli.py add_layer --input layer.json
  python3 mapview_cli.py update_layer --map-id <id> --layer-id <id> [--mode replace|append|upsert] [--name "..."] [--order top|bottom] [--comparison true|false] [--input payload.json]
  python3 mapview_cli.py delete_layer --map-id <id> --layer-id <id>
  python3 mapview_cli.py get_layer_data --map-id <id> --layer-id <id> [--columns a b] [--ids r1 r2] [--offset 0] [--limit 100] [--formatted]
  python3 mapview_cli.py update_map --map-id <id> [--name "..."] [--desc "..."] [--base-map dark] [--center "116.4,39.9"] [--zoom 4] [--share on|off] [--password on|off] [--reset-password]
  python3 mapview_cli.py upload <mapId> <file...> [--name "..."]   # images for attachment columns; prints fileID per file
  python3 mapview_cli.py upload_html <mapId> <file.html> [--name "..."] [--type report]   # host a self-contained page; prints htmlId + public url
  python3 mapview_cli.py delete_html <url>   # delete a hosted page by its url; the link stops working
  python3 mapview_cli.py list_slicers --map-id <id>
  python3 mapview_cli.py update_slicers --map-id <id> --mode add|update|remove|replace [--slicer-id <id>] [--input slicer.json]
  python3 mapview_cli.py geocode --addresses "addr1" "addr2" [--country CN]   # consumes geocoding quota, misses included
  python3 mapview_cli.py region_match --input items.json
  python3 mapview_cli.py get_quota
  python3 mapview_cli.py tools [name]                         # live tool catalog + schemas
  python3 mapview_cli.py call <tool> --json '{"mapId": 1}'    # escape hatch: any tool, JSON args

Complex payloads (add_layer, update_layer, region_match) are read from a JSON
file (--input) or stdin. Each command prints the API response JSON to stdout.
Errors go to stderr with a non-zero exit code.

Local payload builders (no request, no token needed): build canonical
columns/rows JSON from loose agent-side data, then submit it through any
channel (add_layer here, the MCP tool, or REST):
  python3 mapview_cli.py fmt-columns --input fields.json          # ids pass through verbatim
  python3 mapview_cli.py fmt-rows --columns columns.json --input records.json
  python3 mapview_cli.py fmt-csv --file data.csv --id index       # -> {columns, rows}
  python3 mapview_cli.py convert-coords --from gcj02 --lng 116.41 --lat 39.92     # one point
  python3 mapview_cli.py convert-coords --from gcj02 --input rows.json --lng-col lng --lat-col lat
  # GCJ-02 (Chinese table apps' geolocation fields, Amap/Tencent) and BD-09
  # (Baidu) must become WGS84 before add_layer; the math runs locally.
"""

import argparse
import csv
import datetime
import json
import math
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# The public cloud API base. The gateway routes only the /api/embed/ prefix
# (the bare domain serves the frontend SPA), so the prefix is part of the host.
DEFAULT_HOST = "https://mapview.site/api/embed"

# Build variant self-report — `status` prints it. This file is the full
# build; connector packages ship a separate lite file that reports "lite".
CLI_BUILD = "full"


def _token_file():
    """Per-user plain-text token path: XDG config dir (~/.config) on Linux
    and macOS, %APPDATA% on Windows — standard locations, no third-party
    deps. Read-only for this CLI: it serves as the host-agnostic fallback
    when the current host has no slot in tokens.json, and it is never
    written, so older CLI copies keep reading their copy unchanged."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "mapview", "token")


def _store_file():
    """Per-user multi-host/multi-workspace store (JSON), next to the legacy
    token file."""
    return _token_file() + "s.json"


def _read_plain_token():
    """Read the legacy plain-text token (first line); '' when missing."""
    try:
        with open(_token_file(), "r", encoding="utf-8") as f:
            return f.readline().strip()
    except (OSError, ValueError):
        return ""


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if os.name == "posix":
        try:
            os.chmod(os.path.dirname(path), 0o700)
            os.chmod(path, 0o600)
        except OSError:
            pass


def _load_store():
    """Load the JSON store (source of truth when it exists): {'version': 1,
    'hosts': {host: {'active': orgID, 'orgs': {orgID: {'token': str}}}}}.
    Returns {} when missing/corrupt — callers then fall back to the legacy
    plain-text file."""
    try:
        with open(_store_file(), "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return {}
    try:
        store = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return store if isinstance(store, dict) else {}


def _save_store(store):
    """Persist the JSON store (0600 on POSIX). The legacy plain-text file is
    never written by this CLI — it stays frozen for older CLI copies."""
    try:
        _write_file(
            _store_file(), json.dumps(store, indent=2, ensure_ascii=False) + "\n"
        )
    except OSError as e:
        _die(f"cannot write token store {_store_file()}: {e}")


def _host_slots(store):
    """The current host's slot map from a loaded store."""
    return (store.get("hosts") or {}).get(_resolve_host()) or {}


def _stored_entry():
    """Resolve the stored token for the CURRENT host. Precedence: the JSON
    store's active slot for this host, then the old plain-text file — the
    original single-token behavior, still a live fallback for any host
    without a stored slot (an older CLI copy writing it stays effective).
    Returns (token, source description)."""
    hs = _host_slots(_load_store())
    entry = (hs.get("orgs") or {}).get(hs.get("active")) or {}
    token = entry.get("token", "")
    if token:
        return (
            token,
            f"stored {_store_file()} (host {_resolve_host()}, workspace {hs.get('active')})",
        )
    plain = _read_plain_token()
    if plain:
        return plain, f"stored file {_token_file()} (legacy, host-agnostic)"
    return "", ""


def _active_slot_token():
    """The current host's active slot token ('' when none) — used to report
    replacements without counting the plain-file fallback as a host slot."""
    hs = _host_slots(_load_store())
    entry = (hs.get("orgs") or {}).get(hs.get("active")) or {}
    return entry.get("token", "")


def _store_token(token, org_id="manual"):
    """Persist the token into the CURRENT host's slot for org_id and make it
    the active workspace. The plain file is never written — older CLI copies
    keep reading their copy unchanged."""
    org_id = str(org_id)
    store = _load_store()
    store.setdefault("version", 1)
    hosts = store.setdefault("hosts", {})
    hs = hosts.setdefault(_resolve_host(), {"active": org_id, "orgs": {}})
    hs["orgs"][org_id] = {"token": token}
    hs["active"] = org_id
    _save_store(store)


def _resolve_token():
    """Single source of truth for the access token: the MAPVIEW_PAT env var
    wins over the stored file. Returns (token, source); both empty when
    neither is set."""
    env_pat = os.environ.get("MAPVIEW_PAT", "").strip()
    if env_pat:
        return env_pat, "env var MAPVIEW_PAT"
    return _stored_entry()


def _resolve_host():
    return os.environ.get("MAPVIEW_HOST", DEFAULT_HOST).strip().rstrip("/")


def _config():
    """Resolve access token + host (token precedence lives in _resolve_token)."""
    pat, _source = _resolve_token()
    return pat, _resolve_host()


def _do_request(req, url, not_found_hint=""):
    """Send a prepared request and unwrap the REST envelope."""
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        hint = f" — {not_found_hint}" if not_found_hint and e.code == 404 else ""
        _die(f"HTTP {e.code} from {url}: {detail}{hint}")
    except urllib.error.URLError as e:
        _die(
            f"cannot reach {url}: {e.reason} — the host is built into the "
            "CLI, not stored in any project file; if this persists, ask the "
            "user instead of searching the machine for config"
        )

    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        _die(f"non-JSON response: {raw[:200]}")

    # REST envelope: {code, detail, extra, message, requestID}
    if env.get("code", 0) != 0:
        _die(f"API error (code {env.get('code')}): {env.get('message', raw)}")
    return env.get("detail")


def _mcp(host, pat, method, params=None):
    """POST one JSON-RPC request to the MCP endpoint (/mcp/) and return the
    result object. The server runs stateless (2026-07-28 MCP spec): every
    request is self-contained — no initialize handshake, no session id.
    Transport errors die with the same guidance the REST path used."""
    url = f"{host}/mcp/"
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {pat}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            _die(
                f"HTTP 401 from {url}: {detail} — run `login` to connect, or "
                "`switch` to change workspace"
            )
        _die(f"HTTP {e.code} from {url}: {detail}")
    except urllib.error.URLError as e:
        _die(
            f"cannot reach {url}: {e.reason} — the host is built into the "
            "CLI, not stored in any project file; if this persists, ask the "
            "user instead of searching the machine for config"
        )
    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        _die(f"non-JSON response: {raw[:200]}")
    if env.get("error"):
        err = env["error"]
        _die(f"MCP error (code {err.get('code')}): {err.get('message', raw)}")
    return env.get("result") or {}


def _post(host, pat, path, payload, not_found_hint=""):
    """Call the MCP tool `path` (tools/call on /mcp/) and return the tool's
    JSON payload. The signature matches the old REST helper so every tool
    command keeps working unchanged; upload keeps its multipart endpoint."""
    result = _mcp(host, pat, "tools/call", {"name": path, "arguments": payload or {}})
    text = _tool_result_text(result, path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        _die(f"non-JSON tool result from {path}: {text[:200]}")


def _tool_result_text(result, tool):
    """Extract the text payload of a tools/call result; die on tool errors
    (the server marks them with isError instead of a JSON-RPC error)."""
    if result.get("isError"):
        text = _first_text(result, tool)
        hint = " — run `tools` (no arguments) to list available tools"
        _die(f"tool {tool} failed: {text}{hint if 'not found' in text.lower() else ''}")
    return _first_text(result, tool)


def _first_text(result, tool):
    for item in result.get("content") or []:
        if item.get("type") == "text":
            return item.get("text", "")
    _die(f"tool {tool} returned no text content: {result!r:.200}")


def _encode_multipart(fields, files, boundary):
    """Hand-build a multipart/form-data body (RFC 7578): the stdlib ships no
    multipart encoder, and email.mime would mangle filenames. fields is a
    dict of form values; files is a list of (filename, bytes) parts, all
    under the "files" field name."""
    parts = []
    for name, value in fields.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                f"\r\n\r\n{value}\r\n"
            ).encode("utf-8")
        )
    for filename, data in files:
        safe = filename.replace('"', "'").replace("\r", " ").replace("\n", " ")
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                f'filename="{safe}"\r\nContent-Type: {ctype}\r\n\r\n'
            ).encode("utf-8")
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts)


def _post_multipart(host, pat, path, fields, files):
    """POST a multipart form to an /agent/* endpoint and return the parsed
    envelope — the upload endpoint's transport (binary cannot go through the
    JSON channel; see _post for that one)."""
    boundary = "mapview-cli-" + uuid.uuid4().hex
    url = f"{host}/agent/{path}/"
    req = urllib.request.Request(
        url,
        data=_encode_multipart(fields, files, boundary),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {pat}",
        },
        method="POST",
    )
    return _do_request(req, url)


def _die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


# Mirrors the server's built-in marker icon set (types.allIconTypes / frontend
# BUILTIN_ICONS). "c:"-prefixed custom-upload ids are also valid server-side.
_BUILTIN_ICONS = frozenset(
    (
        "location",
        "circle",
        "square",
        "diamond",
        "triangle",
        "cross",
        "plus",
        "flag",
        "star",
        "love",
        "airport",
        "barrier",
        "bicycle",
        "bus",
        "car",
        "construction",
        "entrance",
        "racetrack",
        "rail",
        "warehouse",
        "attraction",
        "bridge",
        "office",
        "building",
        "college",
        "fuel",
        "hardware",
        "museum",
        "parking",
        "pharmacy",
        "bakery",
        "bar",
        "cafe",
        "clothing",
        "commercial",
        "grocery",
        "hairdresser",
        "restaurant",
        "square-star",
        "suitcase",
    )
)
_DEFAULT_ICON = "location"


def _check_icon_names(payload):
    """Pre-flight the styleValues icon names (add_layer/update_layer payloads).

    An unknown name would make the layer's markers vanish after the server
    writes it — coerce it to the default here and say so, so the caller can
    pick a real name instead. Mutates payload in place."""
    sv = payload.get("styleValues")
    if not isinstance(sv, dict):
        return

    def fix(name):
        if name.startswith("c:") or name in _BUILTIN_ICONS:
            return name
        print(
            'warning: icon "%s" is not a built-in icon; replaced with "%s"' % (name, _DEFAULT_ICON),
            file=sys.stderr,
        )
        return _DEFAULT_ICON

    icon = sv.get("icon")
    if isinstance(icon, str) and icon:
        sv["icon"] = fix(icon)
    icons = sv.get("icons")
    if isinstance(icons, list):
        sv["icons"] = [fix(n) if isinstance(n, str) and n else n for n in icons]


def _read_json_input(args):
    """Read a JSON payload from --input <file> or stdin."""
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            return json.load(f)
    raw = sys.stdin.read()
    if not raw.strip():
        _die("no input: provide --input <file> or pipe JSON via stdin")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"invalid JSON input: {e}")


def _read_optional_json_input(args):
    """Like _read_json_input, but an empty stdin (non-TTY callers with nothing
    piped, e.g. agents/CI) yields {} so flag-only update_layer calls work."""
    if args.input:
        return _read_json_input(args)
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"invalid JSON input: {e}")


def _require_pat():
    pat, host = _config()
    if not pat:
        _die(
            "No access token found. Connect one (guided) with: "
            "python3 mapview_cli.py login  — it prints a login link and "
            "stores the token automatically."
        )
    return pat, host


# --- formatters (local payload builders, ADR 0011) ---------------------------
#
# fmt-columns / fmt-rows / fmt-csv convert agent-side data into the canonical
# columns/rows JSON the write API requires. They are pure-local shape
# converters: column ids always come from the input (datasource id, index, or
# a unique column name) and pass through verbatim — never generated, never
# mapped. Structural errors and vocabulary violations fail here (first line
# of defense) so a bad payload never reaches the server.

# Built-in snapshot of the server vocabularies. The fmt-* commands validate
# locally against this snapshot — no request, no token. When the server
# rejects a value anyway, its error lists the accepted options.
_VOCAB_FALLBACK = {
    "columnTypes": [
        "multiLineText",
        "hyperlink",
        "number",
        "datetime",
        "singleChoice",
        "boolean",
        "attachment",
    ],
    "choiceColors": [
        "redLight",
        "redLighter",
        "salmonLight",
        "salmonLighter",
        "orangeLight",
        "orangeLighter",
        "yellowLight",
        "yellowLighter",
        "greenLight",
        "greenLighter",
        "cyanLight",
        "cyanLighter",
        "blueLight",
        "blueLighter",
        "purpleLight",
        "purpleLighter",
        "lilacLight",
        "lilacLighter",
        "greyLight",
        "greyLighter",
        "redDark",
        "salmonDark",
        "orangeDark",
        "yellowDark",
        "greenDark",
        "cyanDark",
        "blueDark",
        "purpleDark",
        "lilacDark",
        "greyDark",
    ],
    "maxColumns": 100,
    "maxRows": 10000,
    "maxChoiceValues": 100,
}

_BOOL_WORDS = {"true", "false", "yes", "no", "是", "否"}
_DT_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)
_CN_DATE_RE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
_NUM_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _vocab_set(vocab, key):
    vals = vocab.get(key)
    if isinstance(vals, list) and vals:
        return set(str(v) for v in vals)
    return set(_VOCAB_FALLBACK.get(key, ()))


def _vocab_int(vocab, key):
    val = vocab.get(key)
    return val if isinstance(val, int) and val > 0 else _VOCAB_FALLBACK.get(key, 0)


def _looks_number(s):
    """Conservative number shape: plain digits/decimal only. Leading zeros
    (codes like \"007\"), >15 significant digits (float64 precision) and
    anything with letters/symbols (¥1,234, 15%) stay text — declare those
    columns explicitly."""
    if not _NUM_RE.fullmatch(s):
        return False
    int_part = s.lstrip("+-").split(".")[0]
    if len(int_part) > 1 and int_part[0] == "0":
        return False
    mantissa = s.lstrip("+-").replace(".", "", 1)
    return len(mantissa.lstrip("0")) <= 15


def _looks_datetime(s):
    """Only unambiguous year-first shapes infer datetime — \"3.14\" and
    \"3/14\" never do (they would silently mean March 14)."""
    if not re.match(r"^\d{4}[-/]", s):
        return False
    for fmt in _DT_FORMATS:
        try:
            datetime.datetime.strptime(s, fmt)
            return True
        except ValueError:
            continue
    m = _CN_DATE_RE.match(s)
    if m:
        return 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31
    return False


def _infer_type(values):
    """Best-effort column type over non-empty sample values: a type is picked
    only when EVERY value fits; multiLineText is the safe fallback. An
    explicit type always wins — this only fills gaps."""
    vals = [str(v).strip() for v in values if v is not None and str(v).strip() != ""]
    if not vals:
        return "multiLineText"
    if all(v in _BOOL_WORDS for v in vals):
        return "boolean"
    if all(_looks_number(v) for v in vals):
        return "number"
    if all(_looks_datetime(v) for v in vals):
        return "datetime"
    return "multiLineText"


def _sample_values(records, column_id):
    return [r.get(column_id) for r in records if isinstance(r, dict)]


def _validate_choice_colors(column_id, opts, colors_ok):
    """Choice colors use palette names (redLight, blueDark, …) — hex or other
    junk would store verbatim and degrade at render time."""
    if not isinstance(opts, dict):
        return
    choices = opts.get("choices")
    if not isinstance(choices, list):
        return
    for ch in choices:
        if isinstance(ch, dict):
            color = ch.get("color")
            if color and str(color) not in colors_ok:
                _die(
                    f"column {column_id!r}: unknown choice color {color!r} — "
                    "use a choiceColors palette name (e.g. light, coral)"
                )


def _load_columns_ref(path):
    """Load the columns baseline: a bare columns array, or a get_layer_data
    response ({columns: [...], rows: ...}) — both work."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _die(f"cannot read --columns {path!r}: {e}")
    if isinstance(data, dict) and isinstance(data.get("columns"), list):
        data = data["columns"]
    if not isinstance(data, list) or not data:
        _die(
            f"--columns {path!r}: expected a JSON array of column objects (or a get_layer_data response)"
        )
    ids = []
    for c in data:
        if isinstance(c, dict) and c.get("id") not in (None, ""):
            ids.append(str(c["id"]))
        else:
            _die(
                f"--columns {path!r}: entry without an id: {json.dumps(c, ensure_ascii=False)[:120]}"
            )
    return ids


# --- coordinate conversion (local: GCJ-02/BD-09 -> WGS84) -------------------
#
# MapView stores and renders WGS84 only. Geolocation fields of Chinese table
# apps (Feishu, DingTalk, WeCom, Tencent Docs/Sheets) and any Amap/Tencent
# data are GCJ-02; Baidu data is BD-09. Submitted raw, points land 100-700 m
# off in China — convert BEFORE add_layer. Plain lng/lat number columns of
# unknown origin are a different case: their system is genuinely unknown —
# ask the user where they came from, or submit as WGS84 and say so; never
# convert blindly.
#
# Math: the public Krassovsky-ellipsoid approximation of the (state-secret)
# GCJ-02 shift, as reverse-engineered in googollee/eviltransform and
# wandergis/coordtransform. Kept bit-identical to the backend's
# pkg/ewkt/coordtransform so CLI-converted rows and datasource-connector
# rows land on the same points; inverse accuracy ~1-2 m, far below
# marker-level semantics (the official map APIs only convert TO GCJ-02, not
# from it, so there is no official reference for this direction). Pure local
# computation: no API call, no token. geocode tool output is already WGS84 —
# never convert it again.

_X_PI = math.pi * 3000.0 / 180.0
_KRASS_OFFSET = 0.00669342162296594323  # Krassovsky eccentricity squared
_KRASS_AXIS = 6378245.0  # Krassovsky semi-major axis (meters)


def _out_of_china(lng, lat):
    """Mainland-China bounding box: the GCJ-02 offset is only applied there."""
    return not (72.004 < lng < 135.05 and 3.86 < lat < 53.55)


def _gcj02_delta(lng, lat):
    """The GCJ-02 shift of a WGS84 point, as the shifted (lng, lat)."""
    x, y = lng - 105.0, lat - 35.0
    xpi, ypi = x * math.pi, y * math.pi
    sqrt_x = math.sqrt(abs(x))
    d = 20.0 * math.sin(6.0 * xpi) + 20.0 * math.sin(2.0 * xpi)
    dlat, dlng = d, d
    dlat += 20.0 * math.sin(ypi) + 40.0 * math.sin(ypi / 3.0)
    dlng += 20.0 * math.sin(xpi) + 40.0 * math.sin(xpi / 3.0)
    dlat += 160.0 * math.sin(ypi / 12.0) + 320.0 * math.sin(ypi / 30.0)
    dlng += 150.0 * math.sin(xpi / 12.0) + 300.0 * math.sin(xpi / 30.0)
    dlat *= 2.0 / 3.0
    dlng *= 2.0 / 3.0
    dlat += -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * sqrt_x
    dlng += 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * sqrt_x

    radlat = lat / 180.0 * math.pi
    magic = 1 - _KRASS_OFFSET * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / (
        (_KRASS_AXIS * (1 - _KRASS_OFFSET)) / (magic * sqrtmagic) * math.pi
    )
    dlng = (dlng * 180.0) / (_KRASS_AXIS / sqrtmagic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def _gcj02_to_wgs84(lng, lat):
    """Inverse of the (non-invertible) GCJ-02 shift via the mirror trick:
    treat the input as GCJ-02, compute its offset, and subtract it once."""
    if _out_of_china(lng, lat):
        return lng, lat
    mg_lng, mg_lat = _gcj02_delta(lng, lat)
    return lng * 2 - mg_lng, lat * 2 - mg_lat


def _bd09_to_gcj02(lng, lat):
    x, y = lng - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return z * math.cos(theta), z * math.sin(theta)


_COORD_SYSTEMS = {
    "gcj02": _gcj02_to_wgs84,
    "bd09": lambda lng, lat: _gcj02_to_wgs84(*_bd09_to_gcj02(lng, lat)),
}


# --- subcommands -----------------------------------------------------------


# --- account: login / switch / status / endpoint (full build only) ---------

def _mask(token):
    """Show enough to recognize a token without printing it in full."""
    return f"{token[:12]}…{token[-4:]}" if len(token) > 16 else "***"


def _agent_login_flow(pick=False):
    """Device-flow login: open a login request, show the URL, poll until the
    user finishes in a browser (login/signup/workspace selection as usual),
    then store the delivered token.

    pick=True marks a switch flow: the login page then skips its auto-enter
    of the currently persisted workspace and makes the user pick one."""
    host = _resolve_host()

    req = urllib.request.Request(
        f"{host}/auth/agent/start/",
        data=json.dumps({"pick": True} if pick else {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    detail = _json_request(req)
    request_id = detail.get("requestID", "")
    login_url = detail.get("loginUrl", "")
    expires_in = int(detail.get("expiresIn", 600))
    poll_interval = max(int(detail.get("pollInterval", 1)), 1)
    if not request_id or not login_url:
        _die(f"unexpected /auth/agent/start/ response: {detail}")

    if pick:
        print("Open this link in a browser and pick the workspace to connect to")
        print("(the current workspace is NOT auto-selected):")
    else:
        print("Open this link in a browser to connect (login, signup, and workspace")
        print("selection work exactly as on the website):")
    print(f"  {login_url}")
    print(f"Waiting for you to finish (expires in {max(expires_in // 60, 1)} min)...")
    # Piped stdout is block-buffered; agents read the URL from a background
    # task's output file — without this flush it stays trapped until exit.
    sys.stdout.flush()

    deadline = time.monotonic() + expires_in
    try:
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            qs = urllib.parse.urlencode({"requestID": request_id})
            req = urllib.request.Request(
                f"{host}/auth/agent/status/?{qs}",
                headers={"Accept": "application/json"},
                method="GET",
            )
            detail = _json_request(req)
            status = detail.get("status")
            if status == "authorized":
                token = detail.get("token", "")
                if not token:
                    _die(f"authorized but no token in response: {detail}")
                existing = _active_slot_token()
                org_id = str(detail.get("orgID") or "manual")
                _store_token(token, org_id=org_id)
                suffix = f" (workspace/org {org_id})" if org_id != "manual" else ""
                print(f"Access token saved to {_store_file()}{suffix}")
                if existing and existing != token:
                    print(
                        f"Replaced the previously active token for this host ({_mask(existing)})."
                    )
                effective, _source = _resolve_token()
                if effective and effective != token:
                    print(
                        "Note: MAPVIEW_PAT is set and still takes precedence — unset it to use the stored token."
                    )
                return
            if status == "expired":
                _die("login request expired or was already used — run login again")
        _die("timed out waiting for the login — run login again")
    except KeyboardInterrupt:
        _die("aborted — run login again to restart")


def _json_request(req):
    """Execute a urllib Request and return the REST envelope's detail."""
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        _die(f"HTTP {e.code} from {req.full_url}: {detail}")
    except urllib.error.URLError as e:
        _die(
            f"cannot reach {req.full_url}: {e.reason} — the host is built "
            "into the CLI, not stored in any project file; if this persists, "
            "ask the user instead of searching the machine for config"
        )

    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        _die(f"non-JSON response: {raw[:200]}")
    if env.get("code", 0) != 0:
        _die(f"API error (code {env.get('code')}): {env.get('message', raw)}")
    return env.get("detail")


def cmd_switch(args):
    """Connect to a different workspace: same browser login flow, new token.

    The login link carries the pick flag, so the browser makes the user
    choose a workspace instead of auto-entering the current one. The previous
    workspace's token stays valid server-side (PATs coexist per org); only
    the locally active token is replaced."""
    _agent_login_flow(pick=True)


def cmd_login(args):
    token = args.token
    if token == "-":
        # Explicit opt-in: reading stdin implicitly would hang forever when
        # stdin is an open-but-empty pipe (common under agents/MCP clients).
        token = sys.stdin.read().strip()
    if not token:
        _agent_login_flow()
        return
    existing = _active_slot_token()
    _store_token(token)
    print(
        f"Access token saved to {_store_file()} (host {_resolve_host()}, workspace manual — org unknown for a pasted token)"
    )
    if existing and existing != token:
        print(
            f"Replaced the previously active token for this host ({_mask(existing)})."
        )
    effective, _source = _resolve_token()
    if effective and effective != token:
        print(
            "Note: MAPVIEW_PAT is set and still takes precedence — unset it to use the stored token."
        )


def cmd_status(args):
    """Report the build variant, token presence + source, and the host."""
    print(f"build: {CLI_BUILD}")
    pat, source = _resolve_token()
    if pat:
        print(f"token: {_mask(pat)} (from {source})")
    else:
        print("token: none — connect one (guided) with: python3 mapview_cli.py login")
    host = _resolve_host()
    print(f"host:  {host}")
    # Show every stored workspace on this host: MAPVIEW_HOST selects the
    # host, `switch` (or login) sets which workspace is active.
    store = _load_store()
    if store:
        hs = _host_slots(store)
        for org in sorted((hs.get("orgs") or {})):
            mark = " (active)" if org == hs.get("active") else ""
            print(
                f"stored workspace {org}{mark}: {_mask((hs['orgs'][org] or {}).get('token', ''))}"
            )
    plain = _read_plain_token()
    if plain:
        print(f"plain-file fallback (hosts without a stored slot): {_mask(plain)}")
    if not pat:
        sys.exit(1)


def cmd_endpoint(args):
    """Print the MCP endpoint for the current deployment — the single source
    for the URL agents put into an MCP client config (never hardcode one)."""
    print(_resolve_host() + "/mcp/")


# --- network tool channel: every command maps to MCP tools/call (full) ------

def cmd_create_map(args):
    pat, host = _require_pat()
    payload = {"name": args.name}
    if args.desc:
        payload["desc"] = args.desc
    detail = _post(host, pat, "create_map", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_list_maps(args):
    pat, host = _require_pat()
    detail = _post(host, pat, "list_maps", {})
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_get_quota(args):
    pat, host = _require_pat()
    detail = _post(host, pat, "get_quota", {})
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_get_map(args):
    pat, host = _require_pat()
    detail = _post(host, pat, "get_map", {"mapId": args.map_id})
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_add_layer(args):
    pat, host = _require_pat()
    payload = _read_json_input(args)
    _check_icon_names(payload)
    detail = _post(host, pat, "add_layer", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_update_layer(args):
    pat, host = _require_pat()
    payload = {"mapId": args.map_id, "layerId": args.layer_id}
    if args.mode:
        payload["mode"] = args.mode
    if args.name:
        payload["name"] = args.name
    if args.order:
        payload["order"] = args.order
    if args.comparison is not None:
        payload["comparison"] = args.comparison == "true"
    # Optional JSON payload (--input file or piped stdin) carries rows/columns/
    # fieldMappings/styleValues; simple flags above take precedence. An empty
    # stdin (non-TTY with nothing piped) is fine for flag-only updates.
    extra = _read_optional_json_input(args)
    for k, v in extra.items():
        payload.setdefault(k, v)
    _check_icon_names(payload)
    detail = _post(host, pat, "update_layer", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_get_layer_data(args):
    pat, host = _require_pat()
    payload = {"mapId": args.map_id, "layerId": args.layer_id}
    if args.columns:
        payload["columns"] = args.columns
    if args.ids:
        payload["ids"] = args.ids
    if args.offset:
        payload["offset"] = args.offset
    if args.limit:
        payload["limit"] = args.limit
    if args.formatted:
        payload["formatted"] = True
    detail = _post(host, pat, "get_layer_data", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_update_map(args):
    pat, host = _require_pat()
    payload = {"mapId": args.map_id}
    for key, value in (
        ("name", args.name),
        ("desc", args.desc),
        ("baseMap", args.base_map),
        ("center", args.center),
    ):
        if value:
            payload[key] = value
    if args.zoom:
        payload["zoom"] = args.zoom
    if args.share:
        payload["share"] = args.share == "on"
    if args.password:
        payload["password"] = args.password == "on"
    if args.reset_password:
        payload["resetPassword"] = True
    detail = _post(host, pat, "update_map", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_delete_layer(args):
    pat, host = _require_pat()
    detail = _post(
        host, pat, "delete_layer", {"mapId": args.map_id, "layerId": args.layer_id}
    )
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_geocode(args):
    pat, host = _require_pat()
    payload = {"addresses": args.addresses}
    if args.country:
        payload["country"] = args.country
    detail = _post(host, pat, "geocode", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_search_places(args):
    pat, host = _require_pat()
    payload = {"query": args.query}
    if args.city:
        payload["city"] = args.city
    if args.limit is not None:
        payload["limit"] = args.limit
    if args.location:
        payload["location"] = args.location
    if args.radius is not None:
        payload["radius"] = args.radius
    detail = _post(host, pat, "search_places", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_region_match(args):
    pat, host = _require_pat()
    payload = _read_json_input(args)
    detail = _post(host, pat, "region_match", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_list_slicers(args):
    pat, host = _require_pat()
    detail = _post(host, pat, "list_slicers", {"mapId": args.map_id})
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_update_slicers(args):
    pat, host = _require_pat()
    payload = {"mapId": args.map_id, "mode": args.mode}
    if args.mode == "replace":
        payload["slicers"] = _read_json_input(args)
    elif args.mode == "remove":
        if not args.slicer_id:
            _die("mode remove requires --slicer-id")
        payload["slicer"] = {"id": args.slicer_id}
    else:
        slicer = _read_json_input(args)
        if not isinstance(slicer, dict):
            _die("add/update expect a JSON object; replace expects an array")
        if args.slicer_id:
            slicer["id"] = args.slicer_id
        payload["slicer"] = slicer
    detail = _post(host, pat, "update_slicers", payload)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_upload_html(args):
    """Host a self-contained HTML document on a map and get its public
    viewer URL — anyone with the link opens it in a browser, no login,
    independent of the map's sharing switch. The file must be fully
    self-contained (inline CSS/JS, data: URI images; max 5MB). No update:
    re-hosting yields a new URL — delete_html the old one when replacing."""
    pat, host = _require_pat()
    try:
        with open(args.file, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError as e:
        _die(f"cannot read {args.file!r}: {e}")
    if not html.strip():
        _die(f"{args.file!r} is empty")
    if len(html.encode("utf-8")) > 5 * 1024 * 1024:
        _die(f"{args.file!r} exceeds 5MB")
    payload = {"mapId": args.map_id, "html": html, "type": args.type}
    if args.name:
        payload["name"] = args.name
    detail = _post(host, pat, "upload_html", payload)
    print(f"{detail.get('htmlId')}  {detail.get('url')}")


def cmd_delete_html(args):
    """Delete a hosted HTML page by passing back its public URL — the exact
    url upload_html printed or get_map listed. The link stops working
    immediately."""
    pat, host = _require_pat()
    detail = _post(host, pat, "delete_html", {"url": args.url})
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def cmd_tools(args):
    pat, host = _require_pat()
    result = _mcp(host, pat, "tools/list")
    catalog = result.get("tools")
    if not isinstance(catalog, list):
        _die(f"unexpected catalog response: {catalog!r}")
    if args.tool:
        entry = next((t for t in catalog if t.get("name") == args.tool), None)
        if entry is None:
            _die(
                f"unknown tool {args.tool!r} — run `tools` with no arguments to list them"
            )
        print(json.dumps(entry, indent=2, ensure_ascii=False))
        return
    for t in catalog:
        desc = (t.get("description") or "").split(". ")[0].strip()
        if len(desc) > 90:
            desc = desc[:87] + "..."
        print(f"{t.get('name')} — {desc}")


def cmd_call(args):
    pat, host = _require_pat()
    if args.json is not None:
        try:
            payload = json.loads(args.json)
        except json.JSONDecodeError as e:
            _die(f"invalid --json payload: {e}")
    else:
        payload = _read_json_input(args)
    detail = _post(
        host,
        pat,
        args.tool,
        payload,
        not_found_hint="run `tools` (no arguments) to list available tools",
    )
    print(json.dumps(detail, ensure_ascii=False, indent=2))


# --- restfile channel: binary upload (full build only) ----------------------

def cmd_upload(args):
    """Upload local image files to a map for attachment columns (info-window
    cover images). This is the only binary command — it posts multipart
    bytes straight to the REST upload endpoint (MCP clients without file
    access use the upload_file MCP tool with base64 content instead).
    Each file comes back as {fileID, fileName, ...}; paste the fileIDs
    into attachment cells. Upload each unique image once and reuse its
    fileID across rows — every upload stores a new object."""
    if args.name and len(args.files) != 1:
        _die("--name is only valid when uploading exactly one file")
    pat, host = _require_pat()
    files = []
    for p in args.files:
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError as e:
            _die(f"cannot read {p!r}: {e}")
        files.append((args.name or os.path.basename(p), data))
    detail = _post_multipart(
        host, pat, "upload_file", {"mapId": str(args.map_id)}, files
    )
    uploaded = detail.get("files") if isinstance(detail, dict) else None
    if not isinstance(uploaded, list) or not uploaded:
        _die(f"unexpected upload response: {detail!r}")
    for f in uploaded:
        if isinstance(f, dict):
            print(f"{f.get('fileID')}  {f.get('fileName')}")


# --- local builders: fmt-* + convert-coords (shared with the lite build) ----

def cmd_fmt_columns(args):
    data = _read_json_input(args)
    if not isinstance(data, list) or not data:
        _die("fmt-columns: input must be a non-empty JSON array of column objects")

    vocab = _VOCAB_FALLBACK
    types_ok = _vocab_set(vocab, "columnTypes")
    colors_ok = _vocab_set(vocab, "choiceColors")
    max_cols = _vocab_int(vocab, "maxColumns")

    sample = None
    if args.rows:
        try:
            with open(args.rows, "r", encoding="utf-8") as f:
                sample = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _die(f"cannot read --rows {args.rows!r}: {e}")
        if not isinstance(sample, list):
            _die("--rows must be a JSON array of record objects")

    seen = set()
    inferred = []
    out = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            _die(f"column {i}: expected an object, got {type(item).__name__}")
        cid = item.get("id")
        if cid is None or str(cid).strip() == "":
            _die(
                f"column {i}: missing 'id' — the id must come from your data "
                "(datasource field id, an index, or a unique column name); it "
                "is passed through verbatim and never generated here"
            )
        cid = str(cid)
        if cid in seen:
            _die(f"duplicate column id {cid!r}")
        seen.add(cid)

        ctype = item.get("type")
        if ctype is None or str(ctype).strip() == "":
            if args.strict:
                _die(f"column {cid!r}: no type and --strict forbids inference")
            ctype = (
                _infer_type(_sample_values(sample, cid)) if sample else "multiLineText"
            )
            inferred.append((cid, ctype))
        ctype = str(ctype)
        if ctype not in types_ok:
            _die(
                f"column {cid!r}: unknown type {ctype!r} "
                f"(valid: {', '.join(sorted(types_ok))})"
            )

        col = {"id": cid, "name": str(item.get("name") or cid), "type": ctype}
        opts = item.get("typeOptions")
        if opts is not None:
            _validate_choice_colors(cid, opts, colors_ok)
            col["typeOptions"] = opts
        out.append(col)

    if len(out) > max_cols:
        _die(f"too many columns: {len(out)} (max {max_cols})")
    for cid, t in inferred:
        print(
            f"inferred type: column {cid!r} -> {t} (declare an explicit type to override)",
            file=sys.stderr,
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_fmt_rows(args):
    records = _read_json_input(args)
    if not isinstance(records, list) or not records:
        _die("fmt-rows: input must be a non-empty JSON array of record objects")

    vocab = _VOCAB_FALLBACK
    max_rows = _vocab_int(vocab, "maxRows")
    ids = set(_load_columns_ref(args.columns))
    id_is_column = "id" in ids
    if id_is_column:
        print(
            'note: a declared column is literally named "id" — flat records '
            'route their "id" value into that column; to pass a row id too, '
            'use {"id": ..., "cells": {...}}',
            file=sys.stderr,
        )

    out = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            _die(f"row {i}: expected an object, got {type(rec).__name__}")
        rid = rec.get("id")
        has_cells = isinstance(rec.get("cells"), dict)
        # "id" normally addresses the row; when a declared column is
        # literally named "id", a flat record's "id" value is that column's
        # cell instead, so it is never silently swallowed.
        id_as_cell = id_is_column and not has_cells
        cells = dict(rec["cells"]) if has_cells else {}
        for k, v in rec.items():
            if k == "cells":
                continue
            if k == "id" and not id_as_cell:
                continue
            cells[k] = v
        unknown = sorted(k for k in cells if k not in ids)
        if unknown:
            _die(
                f"row {i}: keys {unknown} match no declared column id "
                f"(declared: {sorted(ids)}) — fix the record keys or the "
                "--columns baseline"
            )
        row = {"cells": cells}
        if not id_as_cell and rid is not None and str(rid).strip() != "":
            row["id"] = str(rid)
        out.append(row)

    if len(out) > max_rows:
        _die(f"too many rows: {len(out)} (max {max_rows}; split into batches)")
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _cell_empty(v):
    """A cell carries no value: None (fmt-csv marks blanks) or blank string."""
    return v is None or (isinstance(v, str) and v.strip() == "")


def cmd_fmt_csv(args):
    try:
        with open(args.file, "r", encoding="utf-8-sig", newline="") as f:
            raw_rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    except OSError as e:
        _die(f"cannot read {args.file!r}: {e}")
    if len(raw_rows) < 1:
        _die("fmt-csv: empty file")
    header, data = raw_rows[0], raw_rows[1:]

    vocab = _VOCAB_FALLBACK
    types_ok = _vocab_set(vocab, "columnTypes")
    colors_ok = _vocab_set(vocab, "choiceColors")
    max_cols = _vocab_int(vocab, "maxColumns")
    max_rows = _vocab_int(vocab, "maxRows")

    names, types = [], []
    for h in header:
        name, ctype = h, None
        if args.typed_header and ":" in h:
            name, _, ctype = h.rpartition(":")
            name, ctype = name.strip(), ctype.strip()
        if not name.strip():
            _die(
                f"header column {len(names) + 1} is unnamed — likely a trailing "
                "comma or an unnamed export column; name it or drop the column"
            )
        names.append(name)
        types.append(ctype or None)

    if args.id == "name":
        seen = set()
        for n in names:
            if n in seen:
                _die(
                    f"duplicate header name {n!r} — column names as ids must be "
                    "unique; rename the column or use --id index"
                )
            seen.add(n)
        col_ids = list(names)
    else:
        col_ids = [str(i) for i in range(len(names))]

    if len(names) > max_cols:
        _die(f"too many columns: {len(names)} (max {max_cols})")

    cols, inferred = [], []
    for idx, (cid, name) in enumerate(zip(col_ids, names)):
        ctype = types[idx]
        if ctype is not None and ctype not in types_ok:
            _die(
                f"column {name!r}: unknown type {ctype!r} "
                f"(valid: {', '.join(sorted(types_ok))})"
            )
        if ctype is None:
            ctype = _infer_type([r[idx] if idx < len(r) else "" for r in data])
            inferred.append((cid or name, ctype))
        cols.append({"id": cid, "name": name, "type": ctype})

    if len(data) > max_rows:
        _die(f"too many rows: {len(data)} (max {max_rows}; split into batches)")
    if not data:
        _die("no data rows under the header — a layer needs at least one row")

    rows = []
    for i, r in enumerate(data):
        if len(r) != len(header):
            _die(
                f"data row {i + 1} (after the header): {len(r)} fields, expected "
                f"{len(header)} — check commas/quotes on that line"
            )
        cells = {}
        for idx, cid in enumerate(col_ids):
            v = r[idx].strip()
            cells[cid] = None if v == "" else v
        rows.append({"cells": cells})

    # The server enforces this rule on every write; blank CSV cells arrive
    # here as None, and whitespace-only strings count as empty too (stricter
    # than the server, in the safe direction). Catch it before any upload.
    empty_cols = [
        c["name"]
        for c in cols
        if all(_cell_empty(r["cells"].get(c["id"])) for r in rows)
    ]
    if empty_cols:
        _die(
            f"columns {empty_cols} are empty in every data row — every declared "
            "column needs at least one non-empty cell (the server rejects the "
            "write); drop the column or fix the export that lost its values"
        )

    for label, t in inferred:
        print(
            f"inferred type: column {label!r} -> {t} (declare an explicit type to override)",
            file=sys.stderr,
        )
    print(json.dumps({"columns": cols, "rows": rows}, ensure_ascii=False, indent=2))


def _to_float(v):
    """Numeric cell -> float; None for anything else (null, blank, text)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip() != "":
        try:
            return float(v)
        except ValueError:
            return None
    return None


def cmd_convert_coords(args):
    """Rewrite GCJ-02/BD-09 coordinates to WGS84 — the system MapView stores
    and renders. Local math only: no request, no token. Convert data from
    Chinese table apps' geolocation fields (Feishu 多维表格, DingTalk, WeCom,
    Tencent Docs/Sheets) and Amap/Tencent/Baidu-sourced lng/lat BEFORE
    add_layer; geocode output is already WGS84."""
    convert = _COORD_SYSTEMS[args.src]

    batch = (
        args.input is not None
        or args.lng_col is not None
        or args.lat_col is not None
        or args.coord_col is not None
    )
    if not batch:
        if args.lng is None or args.lat is None:
            _die(
                "convert-coords: pass a single point (--lng X --lat Y) or a "
                "batch (--input <file|stdin> with --lng-col/--lat-col, or "
                "--coord-col)"
            )
        lng, lat = convert(args.lng, args.lat)
        if (lng, lat) == (args.lng, args.lat):
            print(
                "note: point is outside mainland China — left unchanged",
                file=sys.stderr,
            )
        print(json.dumps({"lng": round(lng, 6), "lat": round(lat, 6)}))
        return

    if args.lng is not None or args.lat is not None:
        _die("single-point flags (--lng/--lat) cannot be combined with batch flags")
    if args.coord_col is not None:
        if args.lng_col is not None or args.lat_col is not None:
            _die("--coord-col replaces --lng-col/--lat-col — pick one style")
    elif args.lng_col is None or args.lat_col is None:
        _die("batch mode needs both --lng-col and --lat-col (or a single --coord-col)")

    data = _read_json_input(args)
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        rows, wrapped = data["rows"], True
    elif isinstance(data, list):
        rows, wrapped = data, False
    else:
        _die(
            "convert-coords input must be a records/rows array "
            "[{...} | {cells: {...}}] or an object with a rows array"
        )

    converted = skipped = outside = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            _die(f"row {i}: expected an object, got {type(row).__name__}")
        # Coordinates sit either in a flat record or inside the canonical
        # {id, cells} row shape (fmt-rows output, get_layer_data response).
        cells = row["cells"] if isinstance(row.get("cells"), dict) else row
        if args.coord_col is not None:
            v = cells.get(args.coord_col)
            parts = v.split(",") if isinstance(v, str) else v
            if not isinstance(parts, list) or len(parts) != 2:
                skipped += 1
                continue
            lng, lat = _to_float(parts[0]), _to_float(parts[1])
            if lng is None or lat is None:
                skipped += 1
                continue
            if _out_of_china(lng, lat):
                outside += 1
                continue
            lng, lat = convert(lng, lat)
            cells[args.coord_col] = (
                f"{round(lng, 6)},{round(lat, 6)}"
                if isinstance(v, str)
                else [round(lng, 6), round(lat, 6)]
            )
            converted += 1
        else:
            lng = _to_float(cells.get(args.lng_col))
            lat = _to_float(cells.get(args.lat_col))
            if lng is None or lat is None:
                skipped += 1
                continue
            if _out_of_china(lng, lat):
                outside += 1
                continue
            lng, lat = convert(lng, lat)
            cells[args.lng_col] = round(lng, 6)
            cells[args.lat_col] = round(lat, 6)
            converted += 1

    payload = json.dumps(data if wrapped else rows, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
    else:
        print(payload)

    summary = [f"converted {converted} row(s) {args.src} -> WGS84"]
    if skipped:
        summary.append(f"{skipped} skipped (missing/non-numeric coordinates)")
    if outside:
        summary.append(f"{outside} outside mainland China left unchanged")
    print("; ".join(summary), file=sys.stderr)
    if converted == 0:
        _die("no row was converted — check the column ids and coordinate values")


# --- argparse --------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        prog="mapview_cli",
        description="MapView CLI — build shareable maps via the MCP endpoint (file upload keeps its multipart endpoint).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- account: login / switch / status / endpoint -------------------------

    p_login = sub.add_parser(
        "login",
        help="Connect this machine: guided browser login (no args) or store a token via --token.",
    )
    p_login.add_argument(
        "--token",
        help="Access token (mapview_pat_...), or '-' to read it from stdin. "
        "No --token at all starts the guided browser login.",
    )
    p_login.set_defaults(func=cmd_login)

    p_switch = sub.add_parser(
        "switch",
        help="Connect to a different workspace: re-run the guided browser login and store the new token.",
    )
    p_switch.set_defaults(func=cmd_switch)

    p_status = sub.add_parser(
        "status", help="Show whether an access token is configured and its source."
    )
    p_status.set_defaults(func=cmd_status)

    p_endpoint = sub.add_parser(
        "endpoint",
        help="Print the MCP endpoint URL for this deployment (for MCP client config).",
    )
    p_endpoint.set_defaults(func=cmd_endpoint)

    # --- network tools: each command maps to one MCP tools/call ---------------

    p_create = sub.add_parser("create_map", help="Create a new map.")
    p_create.add_argument("--name", required=True, help="Map name (1-120 chars).")
    p_create.add_argument("--desc", help="Optional map description.")
    p_create.set_defaults(func=cmd_create_map)

    p_list = sub.add_parser("list_maps", help="List all maps in the workspace.")
    p_list.set_defaults(func=cmd_list_maps)

    p_quota = sub.add_parser(
        "get_quota", help="Read-only quota status (geocoding/maps/rows)."
    )
    p_quota.set_defaults(func=cmd_get_quota)

    p_get = sub.add_parser("get_map", help="Get map details and its layer list.")
    p_get.add_argument("--map-id", required=True, type=int, help="Map ID.")
    p_get.set_defaults(func=cmd_get_map)

    p_layer = sub.add_parser("add_layer", help="Add a data layer to a map.")
    p_layer.add_argument(
        "--input",
        help="JSON file with the add_layer payload (or read from stdin).",
    )
    p_layer.set_defaults(func=cmd_add_layer)

    p_update_layer = sub.add_parser(
        "update_layer",
        help="Update a layer in place: data (replace/append/upsert), style, "
        "name, comparison, order, or popup card.",
    )
    p_update_layer.add_argument("--map-id", required=True, type=int, help="Map ID.")
    p_update_layer.add_argument("--layer-id", required=True, help="Layer ID.")
    p_update_layer.add_argument(
        "--mode",
        choices=["replace", "append", "upsert"],
        help="Data update mode (default replace).",
    )
    p_update_layer.add_argument("--name", help="New layer name.")
    p_update_layer.add_argument(
        "--order",
        choices=["top", "bottom"],
        help="Move the layer within the map's layer order: top renders above "
        "the other layers; bottom is the default-shown position for "
        "comparison groups.",
    )
    p_update_layer.add_argument(
        "--comparison",
        choices=["true", "false"],
        help="Toggle comparison-group membership (single-select switch in the legend).",
    )
    p_update_layer.add_argument(
        "--input",
        help="Optional JSON file with rows/columns/fieldMappings/styleValues (or stdin).",
    )
    p_update_layer.set_defaults(func=cmd_update_layer)

    p_get_data = sub.add_parser(
        "get_layer_data", help="Read back a layer's columns and rows (paged)."
    )
    p_get_data.add_argument("--map-id", required=True, type=int, help="Map ID.")
    p_get_data.add_argument("--layer-id", required=True, help="Layer ID.")
    p_get_data.add_argument("--columns", nargs="+", help="Column-id projection.")
    p_get_data.add_argument("--ids", nargs="+", help="Row-id filter.")
    p_get_data.add_argument("--offset", type=int, default=0, help="Page offset.")
    p_get_data.add_argument(
        "--limit", type=int, help="Page size (default 100, max 1000)."
    )
    p_get_data.add_argument(
        "--formatted",
        action="store_true",
        help="Also return displayText per row (display-ready strings).",
    )
    p_get_data.set_defaults(func=cmd_get_layer_data)

    p_update_map = sub.add_parser(
        "update_map", help="Update map name/description/basemap/viewport."
    )
    p_update_map.add_argument("--map-id", required=True, type=int, help="Map ID.")
    p_update_map.add_argument("--name", help="New map name.")
    p_update_map.add_argument("--desc", help="New map description.")
    p_update_map.add_argument(
        "--base-map",
        help="Basemap look: standard, light, dark, satellite, or a #rrggbb solid color.",
    )
    p_update_map.add_argument("--center", help='Viewport center "lng,lat".')
    p_update_map.add_argument("--zoom", type=float, help="Viewport zoom (1-20).")
    p_update_map.add_argument(
        "--share",
        choices=["on", "off"],
        help="Turn the share link on or off (maps from create_map are shared by default; "
        "web-editor maps may not be — publish them with --share on).",
    )
    p_update_map.add_argument(
        "--password",
        choices=["on", "off"],
        help="Turn the share password on or off (server-generated; the cleartext password comes back in the response).",
    )
    p_update_map.add_argument(
        "--reset-password",
        action="store_true",
        help="Regenerate the share password.",
    )
    p_update_map.set_defaults(func=cmd_update_map)

    p_delete = sub.add_parser("delete_layer", help="Delete a layer from a map.")
    p_delete.add_argument("--map-id", required=True, type=int, help="Map ID.")
    p_delete.add_argument("--layer-id", required=True, help="Layer ID to delete.")
    p_delete.set_defaults(func=cmd_delete_layer)

    p_upload_html = sub.add_parser(
        "upload_html",
        help="Host a self-contained HTML file on a map; prints htmlId + the public viewer URL.",
    )
    p_upload_html.add_argument("map_id", type=int, help="Map ID.")
    p_upload_html.add_argument(
        "file",
        help="HTML file path — must be fully self-contained (inline CSS/JS, data: URI images; max 5MB).",
    )
    p_upload_html.add_argument(
        "--name", help="Stored document name (≤200 chars; default: no name)."
    )
    p_upload_html.add_argument(
        "--type",
        default="report",
        help="Page type — selects the frontend page the URL opens (only 'report' today).",
    )
    p_upload_html.set_defaults(func=cmd_upload_html)

    p_delete_html = sub.add_parser(
        "delete_html",
        help="Delete a hosted HTML page by its public URL; the link stops working.",
    )
    p_delete_html.add_argument(
        "url",
        help="The hosted page URL — exactly what upload_html printed or get_map listed.",
    )
    p_delete_html.set_defaults(func=cmd_delete_html)

    p_geo = sub.add_parser(
        "geocode",
        help="Geocode addresses to coordinates. Each call consumes the "
        "workspace's geocoding quota, misses included — tell the user "
        "before the first call of a session (get_quota shows the balance).",
    )
    p_geo.add_argument(
        "--addresses", nargs="+", required=True, help="Address strings (≤100)."
    )
    p_geo.add_argument("--country", help="ISO alpha-2 country code (e.g. CN, US).")
    p_geo.set_defaults(func=cmd_geocode)

    p_search = sub.add_parser(
        "search_places",
        help="Keyword POI search (shops, landmarks, facilities…). For a "
        'nearby/around search add --location "lng,lat" (e.g. --location '
        '"121.4737,31.2304" --radius 3000) instead of searching city-wide. '
        "Each call consumes one unit of the workspace's monthly search quota "
        "— tell the user before the first call of a session (get_quota shows "
        "the balance); a quota-refusal error is retryable, not final.",
    )
    p_search.add_argument(
        "--query",
        required=True,
        help="Search keywords: a POI name, brand or category (e.g. 星巴克, 博物馆).",
    )
    p_search.add_argument("--city", help="City name to scope the search (e.g. 上海).")
    p_search.add_argument(
        "--limit",
        type=int,
        help="Max results (default 10; capped at 25 on amap / 10 on mapbox).",
    )
    p_search.add_argument(
        "--location",
        help='Nearby-search center "lng,lat" (e.g. "121.4737,31.2304") — in '
        "the engine's coordinate system (GCJ-02 on amap, WGS84 on mapbox); "
        "with it every amap poi carries distance in meters.",
    )
    p_search.add_argument(
        "--radius",
        type=int,
        help="Search radius in meters around --location (amap only: 1-50000, "
        "default 5000; ignored by mapbox).",
    )
    p_search.set_defaults(func=cmd_search_places)

    p_region = sub.add_parser("region_match", help="Match region names to UIDs.")
    p_region.add_argument(
        "--input", help="JSON file with {items: [...]} (or read from stdin)."
    )
    p_region.set_defaults(func=cmd_region_match)

    p_list_slicers = sub.add_parser(
        "list_slicers", help="List the map's slicers (interactive filter controls)."
    )
    p_list_slicers.add_argument("--map-id", required=True, type=int, help="Map ID.")
    p_list_slicers.set_defaults(func=cmd_list_slicers)

    p_slicers = sub.add_parser(
        "update_slicers",
        help="Add, update, remove, or reorder the map's slicers (interactive filter controls).",
    )
    p_slicers.add_argument("--map-id", required=True, type=int, help="Map ID.")
    p_slicers.add_argument(
        "--mode",
        required=True,
        choices=["add", "update", "remove", "replace"],
        help="add: append; update: replace wholesale by id; remove: delete by id; replace: rebuild the full list (order = display order).",
    )
    p_slicers.add_argument(
        "--slicer-id",
        help="Slicer id (required for remove; sets/overrides the id in --input for update).",
    )
    p_slicers.add_argument(
        "--input",
        help="JSON file with the slicer object (add/update) or the full slicer array (replace); or read from stdin.",
    )
    p_slicers.set_defaults(func=cmd_update_slicers)

    p_tools = sub.add_parser(
        "tools",
        help="List the server's live tool catalog (authoritative; includes tools newer than this CLI).",
    )
    p_tools.add_argument(
        "tool",
        nargs="?",
        default=None,
        help="Print this tool's full description and input schema.",
    )
    p_tools.set_defaults(func=cmd_tools)

    p_call = sub.add_parser(
        "call",
        help="Call any tool with a JSON payload (works for every tool, including ones without a typed subcommand).",
    )
    p_call.add_argument("tool", help="Tool name — see `tools`.")
    g_call = p_call.add_mutually_exclusive_group(required=True)
    g_call.add_argument(
        "--json", help="Inline JSON payload, e.g. --json '{\"mapId\": 1}'."
    )
    g_call.add_argument("--input", help="Read the JSON payload from a file (or stdin).")
    p_call.set_defaults(func=cmd_call)

    # --- local builders: fmt-* + convert-coords -------------------------------

    p_fmt_columns = sub.add_parser(
        "fmt-columns",
        help="LOCAL: format loose column definitions into canonical columns JSON for add_layer/update_layer.",
    )
    p_fmt_columns.add_argument(
        "--input",
        help="JSON file (or stdin) with column objects [{id, name?, type?, typeOptions?}] — id required, passed through verbatim.",
    )
    p_fmt_columns.add_argument(
        "--rows",
        help="Optional records file used as the inference sample when 'type' is omitted.",
    )
    p_fmt_columns.add_argument(
        "--strict",
        action="store_true",
        help="Reject missing types instead of inferring.",
    )
    p_fmt_columns.set_defaults(func=cmd_fmt_columns)

    p_fmt_rows = sub.add_parser(
        "fmt-rows",
        help="LOCAL: format records into canonical rows JSON (cells keyed by column id).",
    )
    p_fmt_rows.add_argument(
        "--columns",
        required=True,
        help="Columns JSON: fmt-columns/fmt-csv output or a get_layer_data response.",
    )
    p_fmt_rows.add_argument(
        "--input",
        help='Records file (or stdin): [{"<columnId>": value, "id": "row-id"?}, ...].',
    )
    p_fmt_rows.set_defaults(func=cmd_fmt_rows)

    p_fmt_csv = sub.add_parser(
        "fmt-csv",
        help="LOCAL: one-shot CSV file -> canonical {columns, rows}.",
    )
    p_fmt_csv.add_argument(
        "--file", required=True, help="CSV file (first row = header)."
    )
    p_fmt_csv.add_argument(
        "--id",
        choices=["index", "name"],
        default="index",
        help='Column id source: position index ("0","1",…, stable while column order holds) or header name (must be unique).',
    )
    p_fmt_csv.add_argument(
        "--typed-header",
        action="store_true",
        help='Header carries inline types: "销售额:number,开业日期:datetime".',
    )
    p_fmt_csv.set_defaults(func=cmd_fmt_csv)

    p_conv = sub.add_parser(
        "convert-coords",
        help="LOCAL: convert GCJ-02/BD-09 to WGS84 coordinates — required for "
        "geolocation fields from Chinese table apps (Feishu, DingTalk, WeCom, "
        "Tencent Docs/Sheets) and Amap/Tencent (GCJ-02) or Baidu (BD-09) data; "
        "geocode output is already WGS84. Pure local math, no API call.",
    )
    p_conv.add_argument(
        "--from",
        required=True,
        choices=["gcj02", "bd09"],
        dest="src",
        help="Source coordinate system of the data.",
    )
    p_conv.add_argument("--lng", type=float, help="Single point: longitude.")
    p_conv.add_argument("--lat", type=float, help="Single point: latitude.")
    p_conv.add_argument(
        "--input",
        help="Batch: JSON file (or stdin) — a records array, canonical rows "
        "[{cells: {...}}], or an object with a rows array (get_layer_data).",
    )
    p_conv.add_argument(
        "--lng-col",
        help="Batch: longitude column id (numbers or numeric strings).",
    )
    p_conv.add_argument("--lat-col", help="Batch: latitude column id.")
    p_conv.add_argument(
        "--coord-col",
        help='Batch: combined "lng,lat" string column — alternative to '
        "--lng-col/--lat-col; the cell keeps its string shape.",
    )
    p_conv.add_argument(
        "--out",
        help="Batch: output file (default stdout; may equal --input).",
    )
    p_conv.set_defaults(func=cmd_convert_coords)

    # --- restfile: binary upload ----------------------------------------------

    p_upload = sub.add_parser(
        "upload",
        help="Upload image files to a map (attachment columns); prints fileID + fileName per file.",
    )
    p_upload.add_argument("map_id", type=int, help="Map ID.")
    p_upload.add_argument(
        "files",
        nargs="+",
        help="Image file paths (jpg/jpeg/png/gif/webp — no bmp/svg; max 20 files, 5MB each, 100MB total per call).",
    )
    p_upload.add_argument(
        "--name",
        help="Stored file name (only valid when uploading exactly one file).",
    )
    p_upload.set_defaults(func=cmd_upload)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
