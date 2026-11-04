"""File writers: CSV (single file or ZIP of tables), XLSX (one sheet per table) and JSON.

Spreadsheet outputs escape every text cell that could be read as a formula (docs/14) and
split tables that exceed the XLSX row limit across numbered sheets (docs/11). JSON is a
versioned document with related tables nested under their parent record.
"""

import csv
import io
import json
import zipfile
from datetime import datetime

from openpyxl import Workbook

from apps.imports.parsing import escape_cell

from .families import ExportData, Table

JSON_FORMAT = "itam.export"
JSON_VERSION = 1
# Excel allows 1,048,576 rows per sheet including the header.
XLSX_MAX_DATA_ROWS = 1_048_575


def _spreadsheet_value(value):
    if isinstance(value, bool) or isinstance(value, int | float):
        return value
    return escape_cell(value)


def _csv_bytes(table: Table) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([c.key for c in table.columns])
    for row in table.rows:
        writer.writerow([_spreadsheet_value(row[c.key]) for c in table.columns])
    # UTF-8 with BOM so Excel opens non-ASCII text correctly.
    return buffer.getvalue().encode("utf-8-sig")


def _about_rows(meta: dict, data: ExportData) -> list[tuple[str, str]]:
    rows = [
        ("Export of", meta["family_label"]),
        ("Exported at (UTC)", meta["exported_at"]),
        ("Exported by", meta["exported_by"]),
        ("Scope", meta["scope_label"]),
        ("Filters", json.dumps(meta["filters"], sort_keys=True) if meta["filters"] else ""),
        (f"Rows: {data.main.name}", str(len(data.main.rows))),
    ]
    rows += [(f"Rows: {name}", str(len(t.rows))) for name, t in data.related.items()]
    if data.masked:
        rows.append(("Hidden personal data columns", ", ".join(data.masked)))
    rows.append(("Note", "Records outside your sites are never included."))
    return rows


def write_csv(data: ExportData, meta: dict) -> tuple[bytes, str, str]:
    if not data.related:
        return _csv_bytes(data.main), "csv", "text/csv; charset=utf-8"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{data.main.name}.csv", _csv_bytes(data.main))
        for name, table in data.related.items():
            archive.writestr(f"{name}.csv", _csv_bytes(table))
        about = io.StringIO()
        writer = csv.writer(about, lineterminator="\r\n")
        writer.writerow(["item", "value"])
        writer.writerows((k, escape_cell(v)) for k, v in _about_rows(meta, data))
        archive.writestr("about.csv", about.getvalue().encode("utf-8-sig"))
    return buffer.getvalue(), "zip", "application/zip"


def write_xlsx(data: ExportData, meta: dict, max_rows: int = XLSX_MAX_DATA_ROWS):
    workbook = Workbook(write_only=True)
    for table in (data.main, *data.related.values()):
        chunks = [table.rows[i : i + max_rows] for i in range(0, len(table.rows), max_rows)]
        for number, rows in enumerate(chunks or [[]], start=1):
            title = table.name if number == 1 else f"{table.name}_{number}"
            sheet = workbook.create_sheet(title[:31])
            sheet.append([c.key for c in table.columns])
            for row in rows:
                sheet.append([_spreadsheet_value(row[c.key]) for c in table.columns])
    about = workbook.create_sheet("about")
    for key, value in _about_rows(meta, data):
        about.append([key, escape_cell(value)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return (
        buffer.getvalue(),
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def write_json(data: ExportData, meta: dict) -> tuple[bytes, str, str]:
    nested: dict[str, dict[str, list]] = {}
    for name, table in data.related.items():
        key = data.parent_key[name]
        for row in table.rows:
            child = {k: v for k, v in row.items() if k != key}
            nested.setdefault(name, {}).setdefault(row[key], []).append(child)
    items = []
    for row in data.main.rows:
        item = dict(row)
        for name in data.related:
            item[name] = nested.get(name, {}).get(row["id"], [])
        items.append(item)
    document = {
        "format": JSON_FORMAT,
        "version": JSON_VERSION,
        "family": meta["family"],
        "exported_at": meta["exported_at"],
        "exported_by": meta["exported_by"],
        "scope": meta["scope"],
        "filters": meta["filters"],
        "columns": [c.key for c in data.main.columns],
        "related": list(data.related),
        "masked_columns": data.masked,
        "count": len(items),
        "items": items,
    }
    body = json.dumps(document, ensure_ascii=False, indent=1, default=str).encode("utf-8")
    return body, "json", "application/json"


WRITERS = {"csv": write_csv, "xlsx": write_xlsx, "json": write_json}


def filename(family: str, extension: str, when: datetime) -> str:
    return f"itam-{family}-{when.strftime('%Y%m%d-%H%M%S')}.{extension}"
