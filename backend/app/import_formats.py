"""TEMPLATE-PREP-01: legacy XLS (BIFF) and XML supplier files as rows of text cells.

Same contract as import_parser.rows: (line, [cell text, ...]) with line 1 the header. Cells
keep their source spelling; identifiers stay text; numbers that may already have lost digits
(Excel float precision, scientific formats) are flagged, never "repaired". No formulas are
executed, no network access, no XML DTD or entity processing (such files are refused).
"""

import re
import xml.etree.ElementTree as ET

MAX_COLUMNS = 512
# A DOCTYPE may declare entities (billion laughs, external entities): refused outright.
UNSAFE_XML = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class Cell(str):
    """Text of a cell plus the evidence used by normalize()/warnings."""

    def __new__(cls, text, numeric=False, uncertain=False, excel_format=""):
        obj = super().__new__(cls, text)
        obj.numeric, obj.uncertain_identifier, obj.excel_format = numeric, uncertain, \
            excel_format
        return obj


# --- XLS --------------------------------------------------------------------------------------


def xls_book(path):
    import xlrd

    return xlrd.open_workbook(path, on_demand=True, formatting_info=False)


def xls_sheets(path):
    book = xls_book(path)
    try:
        return book.sheet_names()
    finally:
        book.release_resources()


def xls_cell(cell, datemode):
    import xlrd

    kind, value = cell.ctype, cell.value
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return Cell("")
    if kind == xlrd.XL_CELL_NUMBER:
        if float(value).is_integer() and abs(value) < 1e21:
            text = str(int(value))
        else:
            text = repr(float(value))
        digits = len(text.lstrip("-").split(".")[0])
        # Beyond 15 significant digits a binary float cannot prove the trailing digits.
        return Cell(text, numeric=True, uncertain=digits > 15 or "e" in text.lower())
    if kind == xlrd.XL_CELL_DATE:
        try:
            return Cell(xlrd.xldate.xldate_as_datetime(value, datemode).isoformat())
        except (ValueError, OverflowError):
            return Cell(str(value))
    if kind == xlrd.XL_CELL_BOOLEAN:
        return Cell("1" if value else "0")
    if kind == xlrd.XL_CELL_ERROR:
        return Cell(xlrd.error_text_from_code.get(value, "#ERR"))
    return Cell(str(value))


def xls_rows(path, sheet_name):
    book = xls_book(path)
    try:
        sheet = book.sheet_by_name(sheet_name)
        if sheet.ncols > MAX_COLUMNS:
            raise ValueError("Túl sok oszlop")
        for r in range(sheet.nrows):
            yield r + 1, [xls_cell(c, book.datemode) for c in sheet.row(r)]
    finally:
        book.release_resources()


# --- XML --------------------------------------------------------------------------------------


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def check_xml(path):
    with open(path, "rb") as f:
        head = f.read(1 << 20)
    if UNSAFE_XML.search(head):
        raise ValueError("Az XML DOCTYPE/ENTITY deklarációt tartalmaz; biztonsági okból nem "
                         "dolgozható fel.")


def record_path(path):
    """The most frequent repeated element that has child elements or attributes."""
    check_xml(path)
    counts, compound, stack = {}, set(), []
    for event, element in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if stack:
                compound.add("/".join(stack))  # the parent has a child element
            stack.append(local(element.tag))
            key = "/".join(stack)
            counts[key] = counts.get(key, 0) + 1
            if element.attrib:
                compound.add(key)
        else:
            stack.pop()
            element.clear()
    candidates = [(n, -p.count("/"), p) for p, n in counts.items()
                  if p.count("/") >= 1 and p in compound]
    if not candidates:
        raise ValueError("Az XML-ben nem található ismétlődő termékrekord.")
    return max(candidates)[2]


def flatten(element):
    """[(column, text)] of one record: attributes '@a', leaves by relative path; repeated
    paths become 'path #2', 'path #3' ... so no value is dropped."""
    out, seen = [], {}

    def add(name, value):
        seen[name] = seen.get(name, 0) + 1
        out.append((name if seen[name] == 1 else f"{name} #{seen[name]}", value))

    for key, value in element.attrib.items():
        add("@" + local(key), value)

    def walk(node, prefix):
        children = list(node)
        if not children:
            add(prefix, (node.text or "").strip())
            for key, value in node.attrib.items():
                add(f"{prefix}@{local(key)}", value)
            return
        for key, value in node.attrib.items():
            add(f"{prefix}@{local(key)}", value)
        for child in children:
            walk(child, f"{prefix}/{local(child.tag)}" if prefix else local(child.tag))

    for child in element:
        walk(child, local(child.tag))
    return out


def records(path, target):
    check_xml(path)
    stack = []
    for event, element in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            stack.append(local(element.tag))
            continue
        if "/".join(stack) == target:
            yield element
            element.clear()
        stack.pop()


def xml_settings(path, config):
    target = config.get("record_path") or record_path(path)
    columns = []
    index = {}
    for record in records(path, target):
        for name, _ in flatten(record):
            if name not in index:
                index[name] = len(columns)
                columns.append(name)
                if len(columns) > MAX_COLUMNS:
                    raise ValueError("Túl sok oszlop")
    if not columns:
        raise ValueError("Az XML-rekordokban nincs adat.")
    return {**config, "format": "xml", "record_path": target, "xml_columns": columns,
            "header_line": 1}


def xml_rows(path, config):
    columns = config["xml_columns"]
    position = {c: i for i, c in enumerate(columns)}
    yield 1, [Cell(c) for c in columns]
    for line, record in enumerate(records(path, config["record_path"]), 2):
        row = [Cell("")] * len(columns)
        for name, value in flatten(record):
            if name in position:
                row[position[name]] = Cell(value)
        yield line, row

