"""Create tables and add missing columns. Never drops the database."""
from sqlalchemy import inspect, text

from app.data import models  # noqa: F401  (register tables on db.metadata)
from app.runtime import app, db


def _ensure_schema():
    """
    create_all only (no drop_all — F-Q-03 / P3).
    SQLite create_all does not ADD columns to existing tables — ALTER missing ones.

    SCHEMA CHANGES (additive ALTER):
      Phase A: status, error_message, error_code
      Phase B: layer, step, error_description
    Never renames isProcessed / isQr / quantity (legacy contract).
    """
    db.create_all()
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    if "check" not in table_names:
        return

    existing = {col["name"] for col in inspector.get_columns("check")}
    alterations = []
    column_defs = [
        ("fiscal_document", "ALTER TABLE \"check\" ADD COLUMN fiscal_document TEXT"),
        ("status", "ALTER TABLE \"check\" ADD COLUMN status VARCHAR(20) DEFAULT 'pending'"),
        ("error_message", "ALTER TABLE \"check\" ADD COLUMN error_message VARCHAR(500)"),
        ("error_code", "ALTER TABLE \"check\" ADD COLUMN error_code VARCHAR(50)"),
        ("layer", "ALTER TABLE \"check\" ADD COLUMN layer VARCHAR(20)"),
        ("step", "ALTER TABLE \"check\" ADD COLUMN step VARCHAR(50)"),
        ("error_description", "ALTER TABLE \"check\" ADD COLUMN error_description VARCHAR(500)"),
    ]
    for col_name, stmt in column_defs:
        if col_name not in existing:
            alterations.append(stmt)

    with db.engine.begin() as conn:
        if alterations:
            for stmt in alterations:
                conn.execute(text(stmt))
            app.logger.info(
                "Applied Check schema alterations: %s",
                ", ".join(
                    c for c, _ in column_defs if c not in existing
                ),
            )
        # Backfill status from legacy flags (never leave processed rows as pending)
        conn.execute(text(
            "UPDATE \"check\" SET status = 'done' "
            "WHERE (status IS NULL OR status = 'pending') "
            "AND isProcessed = 1 AND isQr = 1"
        ))
        conn.execute(text(
            "UPDATE \"check\" SET status = 'failed', "
            "error_message = 'legacy pre-QR processed; not re-queued' "
            "WHERE (status IS NULL OR status = 'pending') "
            "AND isProcessed = 1 AND (isQr = 0 OR isQr IS NULL)"
        ))
        conn.execute(text(
            "UPDATE \"check\" SET status = 'pending' "
            "WHERE status IS NULL"
        ))
