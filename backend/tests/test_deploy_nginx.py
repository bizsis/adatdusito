"""SECURITY-01: deploy-time Nginx invariants (upload size chain, HSTS)."""

import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUTER_HTTPS = ROOT / "deploy/nginx/dev.pinfo.hu.https.conf"
OUTER_HTTP = ROOT / "deploy/nginx/dev.pinfo.hu.http.conf"
INNER = ROOT / "frontend/nginx.conf"
APP_FILE_LIMIT = 50_000_000  # import_api: limit("IMPORT_MAX_BYTES", 50_000_000)
UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def body_limit(path):
    values = re.findall(
        r"^\s*client_max_body_size\s+(\d+)([kmg]?)\s*;", path.read_text(), re.I | re.M
    )
    assert len(values) == 1, f"{path.name}: exactly one client_max_body_size expected"
    number, unit = values[0]
    return int(number) * UNITS[unit.lower()]


def largest_legitimate_upload():
    """Multipart body of a maximal supplier import, as the browser sends it."""
    request = httpx.Request(
        "POST",
        "https://dev.pinfo.hu/api/v1/imports/runs",
        data={
            "supplier_id": "2147483647",
            "profile_id": "2147483647",
            "settings": json.dumps(
                {"sheet": "x" * 4096, "header_line": 1, "encoding": "cp1250", "delimiter": ";"}
            ),
        },
        files={"file": ("é" * 120 + ".xlsx", b"\0" * APP_FILE_LIMIT, "application/octet-stream")},
    )
    return len(request.read())


def test_upload_size_chain_is_consistent():
    outer, inner = body_limit(OUTER_HTTPS), body_limit(INNER)
    assert outer == inner == 51 * 1024**2
    body = largest_legitimate_upload()
    overhead = body - APP_FILE_LIMIT
    # Multipart framing is a few KB; keep at least 1 MiB headroom at every proxy.
    assert 0 < overhead < 64 * 1024
    assert body + 1024**2 <= min(outer, inner)


def test_app_limit_default_matches_documented_value():
    source = (ROOT / "backend/app/import_api.py").read_text()
    assert source.count('limit("IMPORT_MAX_BYTES", 50_000_000)') == 2


def test_hsts_on_https_host_only_without_subdomains_or_preload():
    https = OUTER_HTTPS.read_text()
    headers = re.findall(r'add_header\s+Strict-Transport-Security\s+"([^"]+)"\s+always\s*;', https)
    assert headers == ["max-age=31536000"]
    # Locations with their own add_header would silently drop the server-level header.
    for block in re.findall(r"location[^{]*\{([^}]*)\}", https):
        assert "add_header" not in block
    # HSTS must not be sent over plain HTTP (RFC 6797 7.2).
    assert "Strict-Transport-Security" not in OUTER_HTTP.read_text()
    assert "Strict-Transport-Security" not in INNER.read_text()
