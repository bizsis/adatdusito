"""DEPENDENCY-01: multipart/form parsing (python-multipart + Starlette).

Pins the upload behaviour the dependency upgrades must keep (CSV and XLSX
supplier uploads, file-name handling, size limit, malformed bodies end in a
4xx, never a 500) and the parser fixes they must bring.
"""

import io

import pytest
from openpyxl import Workbook

from conftest import login
from test_supplier_import import imports, upload  # noqa: F401


def xlsx_bytes():
    book = Workbook()
    sheet = book.active
    sheet.append(["SKU", "NAME", "QUANTITY"])
    sheet.append(["001", "TV", 1])
    data = io.BytesIO()
    book.save(data)
    return data.getvalue()


def run(client, id):
    r = client.get(f"/api/v1/imports/runs/{id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_csv_and_xlsx_uploads_round_trip(imports):
    c, t, s = imports
    csv = "SKU;NAME;QUANTITY\n001;Televízió;1\n".encode("utf-8")
    id = upload(c, s, csv)
    assert c.get(f"/api/v1/imports/runs/{id}/file").content == csv
    data = xlsx_bytes()
    id = upload(c, s, data, filename="arlista.xlsx")
    assert c.get(f"/api/v1/imports/runs/{id}/file").content == data
    assert run(c, id)["filename"] == "arlista.xlsx"


@pytest.mark.parametrize(
    "name, stored",
    [
        ("../../etc/passwd.csv", "passwd.csv"),
        ("C:\\Users\\x\\lista.csv", "lista.csv"),
        ("ékezetes név.csv", "ékezetes név.csv"),
    ],
)
def test_client_file_names_never_carry_paths(imports, name, stored):
    c, t, s = imports
    r = c.post(
        "/api/v1/imports/runs",
        data={"supplier_id": s},
        files={"file": (name, b"SKU;NAME\n1;A\n", "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert run(c, r.json()["id"])["filename"] == stored


def test_application_size_limit_still_applies(imports, monkeypatch):
    c, t, s = imports
    monkeypatch.setenv("IMPORT_MAX_BYTES", "1000")
    r = c.post(
        "/api/v1/imports/runs",
        data={"supplier_id": s},
        files={"file": ("big.csv", b"x" * 1001, "text/csv")},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "413"


MALFORMED = {
    "no-boundary": ("multipart/form-data", b"--x\r\n\r\n"),
    "wrong-boundary": (
        "multipart/form-data; boundary=abc",
        b'--zzz\r\nContent-Disposition: form-data; name="supplier_id"\r\n\r\n1\r\n--zzz--\r\n',
    ),
    "truncated": (
        "multipart/form-data; boundary=abc",
        b'--abc\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\nSKU',
    ),
    "header-flood": (
        "multipart/form-data; boundary=abc",
        b"--abc\r\n" + b"".join(b"X-H%d: v\r\n" % i for i in range(5000))
        + b'Content-Disposition: form-data; name="supplier_id"\r\n\r\n1\r\n--abc--\r\n',
    ),
    "huge-header": (
        "multipart/form-data; boundary=abc",
        b"--abc\r\nContent-Disposition: form-data; name=\"" + b"n" * 200_000 + b"\"\r\n\r\n1\r\n--abc--\r\n",
    ),
    "long-boundary": ("multipart/form-data; boundary=" + "b" * 400, b"--" + b"b" * 400 + b"--\r\n"),
}


@pytest.mark.parametrize("kind", sorted(MALFORMED))
def test_malformed_multipart_is_a_client_error(imports, kind):
    c, t, s = imports
    content_type, body = MALFORMED[kind]
    r = c.post("/api/v1/imports/runs", content=body, headers={"Content-Type": content_type})
    assert 400 <= r.status_code < 500, (kind, r.status_code, r.text[:200])


def test_urlencoded_semicolon_is_not_a_field_separator():
    """WHATWG form parsing; python-multipart < 0.0.30 split on ';' (GHSA-6jv3-5f52-599m)."""
    from python_multipart import QuerystringParser

    fields = []
    current = {}

    def on_field_name(data, start, end):
        current["name"] = current.get("name", b"") + data[start:end]

    def on_field_data(data, start, end):
        current["value"] = current.get("value", b"") + data[start:end]

    def on_field_end():
        fields.append((current.get("name", b""), current.get("value", b"")))
        current.clear()

    parser = QuerystringParser(
        {"on_field_name": on_field_name, "on_field_data": on_field_data, "on_field_end": on_field_end}
    )
    parser.write(b"a=1;b=2")
    parser.finalize()
    assert fields == [(b"a", b"1;b=2")]


def test_negative_content_length_is_rejected():
    """python-multipart < 0.0.31 read until EOF (GHSA-v9pg-7xvm-68hf)."""
    from python_multipart import parse_form

    with pytest.raises(Exception):
        parse_form(
            {"Content-Type": b"application/x-www-form-urlencoded", "Content-Length": b"-1"},
            io.BytesIO(b"a=1"),
            lambda field: None,
            lambda file: None,
        )


def test_multipart_part_header_count_is_bounded():
    """python-multipart < 0.0.27 had no part-header limit (GHSA-pp6c-gr5w-3c5g)."""
    from python_multipart import MultipartParser

    parser = MultipartParser(b"abc", {})
    body = b"--abc\r\n" + b"".join(b"X-H%d: v\r\n" % i for i in range(20000)) + b"\r\n"
    with pytest.raises(Exception):
        parser.write(body)
