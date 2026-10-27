"""Bounded receipt history and visible admin receipt metadata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
import json
from threading import Event, Thread
from unittest.mock import patch

import pytest


def _check(main, number, *, status, processed_at, qr=None):
    return main.Check(
        name=f"Робот {number}",
        bay=str(number),
        type="1",
        sum=float(number),
        status=status,
        isProcessed=status == main.STATUS_DONE,
        isQr=qr is not None,
        qr=qr,
        dateCreated=processed_at or datetime(2026, 8, 24, 9, 0, 0),
        dateProcessed=processed_at,
    )


def test_prune_keeps_1000_rows_and_never_removes_active_check(app_db):
    main = app_db
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)

    with main.app.app_context():
        main.db.session.add_all(
            [
                _check(
                    main,
                    number,
                    status=main.STATUS_DONE,
                    processed_at=old,
                    qr=f"qr-{number}",
                )
                for number in range(1, main.CHECK_HISTORY_LIMIT + 1)
            ]
        )
        active = _check(
            main,
            main.CHECK_HISTORY_LIMIT + 1,
            status=main.STATUS_PRINTING,
            processed_at=None,
        )
        main.db.session.add(active)
        main.db.session.commit()
        active_id = active.id

        deleted = main._prune_checks_to_limit()

        assert deleted == 1
        assert main.Check.query.count() == main.CHECK_HISTORY_LIMIT
        assert main.db.session.get(main.Check, 1) is None
        assert main.db.session.get(main.Check, active_id) is not None


def test_prune_temporarily_keeps_recent_terminal_and_active_rows(app_db):
    """A live QR waiter and active jobs take priority over the hard row target."""
    main = app_db
    recent = datetime.now(timezone.utc).replace(tzinfo=None)

    with main.app.app_context():
        recent_done = _check(
            main,
            1,
            status=main.STATUS_DONE,
            processed_at=recent,
            qr="recent-qr",
        )
        pending = _check(
            main,
            2,
            status=main.STATUS_PENDING,
            processed_at=None,
        )
        printing = _check(
            main,
            3,
            status=main.STATUS_PRINTING,
            processed_at=None,
        )
        main.db.session.add_all([recent_done, pending, printing])
        main.db.session.commit()
        ids = {recent_done.id, pending.id, printing.id}

        deleted = main._prune_checks_to_limit(limit=2)

        assert deleted == 0
        assert main.Check.query.count() == 3
        assert {row.id for row in main.Check.query.all()} == ids


@pytest.mark.parametrize("wait_by_id", [True, False], ids=["id", "resolved-name"])
def test_live_waiter_survives_prune_despite_wildly_old_processed_time(
    app_db, wait_by_id
):
    """A forward clock step cannot age a row out from under its QR waiter."""
    main = app_db
    waiter_sleeping = Event()
    release_waiter = Event()
    result = {}
    errors = []

    with main.app.app_context():
        row = _check(
            main,
            1,
            status=main.STATUS_PRINTING,
            processed_at=None,
        )
        main.db.session.add(row)
        main.db.session.commit()
        check_id = row.id

    def blocking_sleep(_seconds):
        waiter_sleeping.set()
        if not release_waiter.wait(timeout=5):
            raise TimeoutError("test did not release QR waiter")

    def wait_for_qr():
        try:
            with main.app.app_context():
                result["value"] = main.find_actual_check(
                    "Робот 1",
                    check_id=check_id if wait_by_id else None,
                    timeout_sec=30,
                )
        except BaseException as exc:  # surfaced in the test thread below
            errors.append(exc)

    with patch.object(main.time, "sleep", side_effect=blocking_sleep):
        waiter = Thread(target=wait_for_qr, daemon=True)
        waiter.start()
        try:
            assert waiter_sleeping.wait(timeout=5), "QR waiter never started"
            with main.app.app_context():
                row = main.db.session.get(main.Check, check_id)
                row.status = main.STATUS_DONE
                row.isProcessed = True
                row.isQr = True
                row.qr = "protected-qr"
                # Simulates a large forward wall-clock correction after QR completion.
                row.dateProcessed = datetime(1900, 1, 1, 0, 0, 0)
                main.db.session.commit()

                assert main._prune_checks_to_limit(limit=0) == 0
                assert main.db.session.get(main.Check, check_id) is not None
        finally:
            release_waiter.set()
            waiter.join(timeout=5)

    assert not waiter.is_alive()
    assert errors == []
    assert result["value"]["code"] == 201
    assert result["value"]["qr"] == "protected-qr"
    assert check_id not in main._protected_check_id_counts

    with main.app.app_context():
        assert main._prune_checks_to_limit(limit=0) == 1
        assert main.db.session.get(main.Check, check_id) is None


def test_create_check_protects_id_across_commit_wait_and_error(app_db):
    main = app_db
    observed = {}

    def observe_prune(_context):
        observed["during_prune"] = set(main._protected_check_id_counts)
        return 0

    def fail_wait(_name, check_id=None, timeout_sec=None):
        observed["check_id"] = check_id
        observed["during_wait"] = set(main._protected_check_id_counts)
        raise RuntimeError("synthetic waiter failure")

    import app.http.api as http_api

    with patch.object(http_api, "_prune_checks_safely", side_effect=observe_prune):
        with patch.object(http_api, "find_actual_check", side_effect=fail_wait):
            response = main.app.test_client().post(
                "/create-check",
                headers={
                    "Data": json.dumps(
                        {"name": "1", "bay": "7", "sum": 100, "type": "1"}
                    )
                },
            )

    assert response.status_code == 500
    assert observed["check_id"] in observed["during_prune"]
    assert observed["check_id"] in observed["during_wait"]
    assert observed["check_id"] not in main._protected_check_id_counts


def test_get_checks_returns_at_most_1000_rows(app_db):
    main = app_db

    with main.app.app_context():
        main.db.session.add_all(
            [
                _check(
                    main,
                    number,
                    status=main.STATUS_PENDING,
                    processed_at=None,
                )
                for number in range(1, main.CHECK_HISTORY_LIMIT + 2)
            ]
        )
        main.db.session.commit()

    response = main.app.test_client().get("/get-checks")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload) == main.CHECK_HISTORY_LIMIT
    assert payload[0]["id"] == main.CHECK_HISTORY_LIMIT + 1
    assert payload[-1]["id"] == 2


def test_admin_checks_renders_qr_flag_payload_and_moscow_datetime(app_db):
    main = app_db
    qr_payload = '<script>&"'

    with main.app.app_context():
        generated = _check(
            main,
            1,
            status=main.STATUS_DONE,
            processed_at=datetime(2026, 8, 24, 9, 11, 12),
            qr=qr_payload,
        )
        generated.dateCreated = datetime(2026, 8, 24, 9, 10, 11)
        missing = _check(
            main,
            2,
            status=main.STATUS_PENDING,
            processed_at=None,
        )
        missing.dateCreated = datetime(2026, 8, 24, 10, 10, 11)
        main.db.session.add_all([generated, missing])
        main.db.session.commit()

    response = main.app.test_client().get("/admin/checks")
    raw_page = response.get_data(as_text=True)
    page = unescape(raw_page)

    assert response.status_code == 200
    assert "<th>QR generated</th>" in page
    assert "<th>Дата и время</th>" in page
    assert ">Да<" in page
    assert ">Нет<" in page
    assert "24.08.2026 12:10:11" in page
    assert "24.08.2026 13:10:11" in page
    assert qr_payload in page
    assert "<script>" not in raw_page
    assert "&lt;script&gt;&amp;&#34;" in raw_page


def test_check_json_has_utc_datetime_and_qr_generated_alias(app_db):
    main = app_db

    with main.app.app_context():
        row = _check(
            main,
            1,
            status=main.STATUS_DONE,
            processed_at=datetime(2026, 8, 24, 9, 11, 12),
            qr="receipt-qr",
        )
        row.dateCreated = datetime(2026, 8, 24, 9, 10, 11)
        main.db.session.add(row)
        main.db.session.commit()

    response = main.app.test_client().get("/get-checks")
    payload = response.get_json()[0]

    assert payload["qrGenerated"] is True
    assert payload["isQr"] is True
    assert payload["dateTime"] == "2026-08-24T09:10:11Z"
    assert payload["dateTimeDisplay"] == "24.08.2026 12:10:11"
