"""Trigram indexes for inventory substring search (docs/14: p95 < 2 s at 10k devices).

Django compiles `field__icontains` on PostgreSQL to `UPPER(col::text) LIKE UPPER(%s)`,
so each index is built on that exact expression. pg_trgm is a trusted extension
(PostgreSQL 13+); the database owner can create it. Built non-concurrently, which is
fine at bootstrap; on a large live table rebuild with CREATE INDEX CONCURRENTLY.
"""

from django.db import migrations

INDEXES = [
    ("assets_asset", "name", "assets_asset_name_trgm"),
    ("assets_asset", "asset_tag", "assets_asset_tag_trgm"),
    ("assets_asset", "serial_number", "assets_asset_serial_trgm"),
    ("assets_asset", "manufacturer", "assets_asset_manufacturer_trgm"),
    ("assets_asset", "model", "assets_asset_model_trgm"),
    ("assets_assethostname", "hostname", "assets_hostname_trgm"),
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm", params=None)
    for table, column, name in INDEXES:
        schema_editor.execute(
            f'CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (UPPER("{column}"::text) gin_trgm_ops)',
            params=None,
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for _table, _column, name in INDEXES:
        schema_editor.execute(f"DROP INDEX IF EXISTS {name}", params=None)


class Migration(migrations.Migration):
    dependencies = [("assets", "0006_saved_view")]

    operations = [migrations.RunPython(forwards, backwards)]
