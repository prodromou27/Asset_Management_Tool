"""Database-level append-only guarantee for audit events (PostgreSQL).

Blocks UPDATE and DELETE on audit_auditevent for every DB role the app uses.
Retention purges (future task) must run as a separate, audited maintenance
role that temporarily disables this trigger.
"""

from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION audit_auditevent_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditevent is append-only (% blocked)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_auditevent_append_only ON audit_auditevent;
CREATE TRIGGER audit_auditevent_append_only
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_auditevent_block_mutation();

DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
CREATE TRIGGER audit_auditevent_no_truncate
    BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_auditevent_block_mutation();
"""

DROP = """
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_auditevent_append_only ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_auditevent_block_mutation();
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        # params=None: send verbatim; the PL/pgSQL '%' must not be treated as a placeholder.
        schema_editor.execute(CREATE, params=None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP, params=None)


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunPython(forwards, backwards)]
