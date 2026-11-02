"""Database-level append-only guarantee for asset history (PostgreSQL)."""

from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION assets_history_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'assets_assethistoryentry is append-only (% blocked)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS assets_history_append_only ON assets_assethistoryentry;
CREATE TRIGGER assets_history_append_only
    BEFORE UPDATE OR DELETE ON assets_assethistoryentry
    FOR EACH ROW EXECUTE FUNCTION assets_history_block_mutation();

DROP TRIGGER IF EXISTS assets_history_no_truncate ON assets_assethistoryentry;
CREATE TRIGGER assets_history_no_truncate
    BEFORE TRUNCATE ON assets_assethistoryentry
    FOR EACH STATEMENT EXECUTE FUNCTION assets_history_block_mutation();
"""

DROP = """
DROP TRIGGER IF EXISTS assets_history_no_truncate ON assets_assethistoryentry;
DROP TRIGGER IF EXISTS assets_history_append_only ON assets_assethistoryentry;
DROP FUNCTION IF EXISTS assets_history_block_mutation();
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        # params=None: send verbatim; the PL/pgSQL '%' must not be treated as a placeholder.
        schema_editor.execute(CREATE, params=None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP, params=None)


class Migration(migrations.Migration):
    dependencies = [("assets", "0002_seed_categories")]

    operations = [migrations.RunPython(forwards, backwards)]
