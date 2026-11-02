"""Database-level immutability for raw observations (PostgreSQL)."""

from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION observations_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'observations_observation is immutable (% blocked)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS observations_immutable ON observations_observation;
CREATE TRIGGER observations_immutable
    BEFORE UPDATE OR DELETE ON observations_observation
    FOR EACH ROW EXECUTE FUNCTION observations_block_mutation();

DROP TRIGGER IF EXISTS observations_no_truncate ON observations_observation;
CREATE TRIGGER observations_no_truncate
    BEFORE TRUNCATE ON observations_observation
    FOR EACH STATEMENT EXECUTE FUNCTION observations_block_mutation();
"""

DROP = """
DROP TRIGGER IF EXISTS observations_no_truncate ON observations_observation;
DROP TRIGGER IF EXISTS observations_immutable ON observations_observation;
DROP FUNCTION IF EXISTS observations_block_mutation();
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        # params=None: send verbatim; the PL/pgSQL '%' must not be treated as a placeholder.
        schema_editor.execute(CREATE, params=None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP, params=None)


class Migration(migrations.Migration):
    dependencies = [("observations", "0001_initial")]

    operations = [migrations.RunPython(forwards, backwards)]
