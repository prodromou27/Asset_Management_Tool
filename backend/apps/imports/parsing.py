"""Untrusted CSV/XLSX parsing with hard limits (docs/11, docs/14 "Untrusted file upload").

- Size: ``MAX_BYTES`` per file; rows ``MAX_ROWS``; columns ``MAX_COLUMNS``; cell length
  ``MAX_CELL``.
- CSV: UTF-8 (with or without BOM), falling back to Windows-1252; delimiter sniffed among
  comma, semicolon and tab.
- XLSX: read-only streaming via openpyxl (XML parsed through defusedxml when installed);
  the zip is inspected first and refused when its uncompressed size or compression ratio
  looks like a decompression bomb. Only cell values are read: no formulas are evaluated,
  no macros, external links or images.
- Formula-looking text (``=``, ``+``, ``@``, tab/CR, or ``-`` followed by a function-like
  expression) is rejected per cell by the families and escaped on every output.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_CELL = 10_000
MAX_XLSX_UNCOMPRESSED = 60 * 1024 * 1024
MAX_XLSX_RATIO = 100

_FORMULA = re.compile(r"^(?:[=+@\t\r]|-[^\d\s.,-][^\n]*[(!])")


class ParseError(ValueError):
    pass


@dataclass
class Parsed:
    file_format: str
    headers: list[str]
    rows: list[list[str]]
    encoding: str = ""
    delimiter: str = ""
    sheet: str = ""
    warnings: list[str] = field(default_factory=list)


def looks_like_formula(value: str) -> bool:
    return bool(value) and bool(_FORMULA.match(value))


def escape_cell(value) -> str:
    """For any CSV/XLSX we produce: neutralise formula-looking text (docs/14)."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def _clean_headers(raw: list[str]) -> list[str]:
    headers = [str(h or "").strip()[:100] for h in raw]
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        raise ParseError("The first row must contain column names.")
    if len(headers) > MAX_COLUMNS:
        raise ParseError(f"At most {MAX_COLUMNS} columns are allowed.")
    seen: set[str] = set()
    for n, header in enumerate(headers, start=1):
        if not header:
            raise ParseError(f"Column {n} has no name.")
        if header.lower() in seen:
            raise ParseError(f"Column name {header!r} appears twice.")
        seen.add(header.lower())
    return headers


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    text = str(value).strip()
    if len(text) > MAX_CELL:
        raise ParseError(f"A cell is longer than {MAX_CELL} characters.")
    return text


def _collect(header_row, data_rows) -> tuple[list[str], list[list[str]]]:
    headers = _clean_headers(list(header_row))
    width = len(headers)
    rows: list[list[str]] = []
    for raw in data_rows:
        values = [_cell(v) for v in list(raw)[: width + 50]]
        if any(v for v in values[width:]):
            raise ParseError(f"Row {len(rows) + 2} has values beyond the named columns.")
        values = (values + [""] * width)[:width]
        if not any(values):
            continue  # blank lines are ignored
        rows.append(values)
        if len(rows) > MAX_ROWS:
            raise ParseError(f"At most {MAX_ROWS} data rows are allowed per file.")
    return headers, rows


def _parse_csv(data: bytes) -> Parsed:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes almost anything
        raise ParseError("The file is not UTF-8 or Windows-1252 text.")
    if "\x00" in text:
        raise ParseError("The file contains binary data; save it as CSV or XLSX.")
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ParseError("The file is empty.") from exc
    try:
        headers, rows = _collect(header, reader)
    except csv.Error as exc:
        raise ParseError(f"The CSV could not be read ({exc}).") from exc
    warnings = []
    if encoding == "cp1252":
        warnings.append("The file is not UTF-8; it was read as Windows-1252.")
    return Parsed(
        "csv",
        headers,
        rows,
        encoding="utf-8" if encoding == "utf-8-sig" else encoding,
        delimiter=delimiter,
        warnings=warnings,
    )


def _check_zip(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError("The file is not a valid XLSX workbook.") from exc
    total = 0
    for info in archive.infolist():
        total += info.file_size
        if info.compress_size and info.file_size / info.compress_size > MAX_XLSX_RATIO:
            raise ParseError("The workbook is compressed suspiciously well; refused.")
        if ".." in info.filename or info.filename.startswith("/"):
            raise ParseError("The workbook contains unsafe paths; refused.")
    if total > MAX_XLSX_UNCOMPRESSED:
        raise ParseError("The workbook is too large when uncompressed; refused.")
    if "xl/vbaProject.bin" in archive.namelist():
        raise ParseError("Macro-enabled workbooks are not accepted.")


def _parse_xlsx(data: bytes, sheet: str = "") -> Parsed:
    _check_zip(data)
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parser failure is a user error
        raise ParseError("The workbook could not be read.") from exc
    try:
        names = workbook.sheetnames
        chosen = sheet if sheet in names else names[0]
        rows = workbook[chosen].iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration as exc:
            raise ParseError("The first sheet is empty.") from exc
        headers, data_rows = _collect(header, rows)
    finally:
        workbook.close()
    warnings = []
    if len(names) > 1 and not sheet:
        warnings.append(f"Only the first sheet ({chosen!r}) was read.")
    return Parsed("xlsx", headers, data_rows, sheet=chosen, warnings=warnings)


def parse(data: bytes, filename: str, sheet: str = "") -> Parsed:
    if len(data) > MAX_BYTES:
        raise ParseError(f"Files up to {MAX_BYTES // (1024 * 1024)} MB are accepted.")
    if not data:
        raise ParseError("The file is empty.")
    lower = filename.lower()
    if lower.endswith(".xlsx") or data[:4] == b"PK\x03\x04":
        return _parse_xlsx(data, sheet)
    if lower.endswith((".csv", ".txt")):
        return _parse_csv(data)
    raise ParseError("Upload a .csv or .xlsx file.")
