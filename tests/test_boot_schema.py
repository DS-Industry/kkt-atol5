"""Boot must not wipe DB; schema backfill from legacy flags."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_main_boot_path_has_no_drop_all():
    """Static check: Phase A boot uses create_all / _ensure_schema only (F-Q-03 / P3)."""
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    drop_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Attribute) and func.attr == "drop_all":
                name = "drop_all"
            elif isinstance(func, ast.Name) and func.id == "drop_all":
                name = "drop_all"
            if name:
                drop_calls.append(node.lineno)
    assert drop_calls == [], f"db.drop_all must not appear in main.py (lines {drop_calls})"
    assert "_ensure_schema" in source
    assert "db.create_all" in source or "create_all()" in source


def test_ensure_schema_preserves_rows_on_restart(app_db, tmp_path):
    """Simulate restart: rows survive a second _ensure_schema (no wipe)."""
    main = app_db
    with main.app.app_context():
        row = main.Check(
            name="Робот 9",
            bay="9",
            type="1",
            sum=50.0,
            status=main.STATUS_PENDING,
            isProcessed=False,
            isQr=False,
        )
        main.db.session.add(row)
        main.db.session.commit()
        check_id = row.id

        # "Restart" simulation
        main._ensure_schema()

        surviving = main.db.session.get(main.Check, check_id)
        assert surviving is not None
        assert surviving.name == "Робот 9"
        assert surviving.status == main.STATUS_PENDING


def test_ensure_schema_backfill_legacy_processed_no_qr_to_failed(tmp_path):
    """
    Legacy isProcessed=1 isQr=0 → status failed (not pending), so job never re-prints.
    Exercises the SQL path inside _ensure_schema against a pre-existing table.
    """
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            CREATE TABLE "check" (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                bay VARCHAR(50) NOT NULL,
                price FLOAT,
                quantity INTEGER,
                type VARCHAR(50) NOT NULL,
                sum FLOAT NOT NULL,
                "isProcessed" BOOLEAN,
                "isQr" BOOLEAN,
                "dateCreated" DATETIME,
                "dateProcessed" DATETIME,
                qr VARCHAR(255)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO "check"
            (id, name, bay, type, sum, "isProcessed", "isQr")
            VALUES (1, 'Legacy', '1', '1', 10.0, 1, 0)
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Import main with FakeIFptr already patched by conftest; rebind to legacy DB
    import main
    from tests.conftest import _rebind_sqlite

    with main.app.app_context():
        _rebind_sqlite(main, db_file)
        main._ensure_schema()

        row = main.db.session.get(main.Check, 1)
        assert row is not None
        assert row.status == main.STATUS_FAILED
        assert row.status != main.STATUS_PENDING
        assert "legacy" in (row.error_message or "").lower()
