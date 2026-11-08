"""Small network-disabled, in-memory proof of the library loaded by the release Python."""

import hashlib
import json
import sqlite3
from pathlib import Path


def main():
    provenance = Path("/usr/local/share/itam")
    source = json.loads((provenance / "sqlite-source.json").read_text())
    if sqlite3.sqlite_version != source["version"]:
        raise RuntimeError(f"Unexpected linked SQLite version: {sqlite3.sqlite_version}")
    with sqlite3.connect(":memory:") as db:
        options = sorted(row[0] for row in db.execute("PRAGMA compile_options"))
        required = {"ENABLE_FTS3", "ENABLE_FTS4", "ENABLE_FTS5", "ENABLE_RTREE", "ENABLE_SESSION"}
        if not required.issubset(options):
            raise RuntimeError("Reviewed SQLite compile options are missing")
        db.execute("CREATE VIRTUAL TABLE docs USING fts5(body, detail=none, prefix='2 3')")
        db.executemany(
            "INSERT INTO docs(rowid,body) VALUES (?,?)", [(-1, "network"), (2, "network inventory")]
        )
        count = db.execute("SELECT count(*) FROM docs WHERE docs MATCH 'net*'").fetchone()[0]
        if count != 2:
            raise RuntimeError("SQLite FTS5 prefix/negative-rowid compatibility failed")
        source_id = db.execute("SELECT sqlite_source_id()").fetchone()[0]
    libraries = {
        line.split()[-1]
        for line in Path("/proc/self/maps").read_text().splitlines()
        if "/libsqlite3.so" in line
    }
    if len(libraries) != 1 or not next(iter(libraries)).startswith("/usr/lib/"):
        raise RuntimeError("Linked SQLite library identity is missing or ambiguous")
    library = Path(next(iter(libraries)))
    print(
        json.dumps(
            {
                "passed": True,
                "sqlite_version": sqlite3.sqlite_version,
                "source_id": source_id,
                "compile_options": options,
                "library": str(library),
                "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
                "source": source,
                "recipe_sha256": hashlib.sha256(
                    (provenance / "sqlite-APKBUILD").read_bytes()
                ).hexdigest(),
                "fixture": "in-memory FTS5 prefix search with negative rowid",
            }
        )
    )


if __name__ == "__main__":
    main()
