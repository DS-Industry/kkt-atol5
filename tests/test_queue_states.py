"""Queue lifecycle: pending → printing → done|failed; shift timeout re-queues."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def pending_check(app_db):
    main = app_db
    with main.app.app_context():
        check = main.Check(
            name="Робот 1",
            bay="1",
            type="1",
            sum=100.0,
            status=main.STATUS_PENDING,
            isProcessed=False,
            isQr=False,
        )
        main.db.session.add(check)
        main.db.session.commit()
        return check.id


def test_queue_success_pending_printing_done(app_db, pending_check):
    main = app_db
    check_id = pending_check
    qr_json = json.dumps({"documentTLV": {"qr": "t=20260101T1200&s=100.00&fn=1&i=1&fp=1&n=1"}})

    with main.app.app_context():
        with patch.object(main.cashier_service, "get_shift_status", return_value={"code": 200}):
            with patch.object(
                main.cashier_service, "print_check", return_value={"code": 201}
            ) as mock_print:
                with patch.object(
                    main.cashier_service, "readLastReciept", return_value=qr_json
                ):
                    main.job1()

        check = main.db.session.get(main.Check, check_id)
        assert check is not None
        assert check.status == main.STATUS_DONE
        assert check.isProcessed is True
        assert check.isQr is True
        assert check.qr is not None
        mock_print.assert_called_once()


def test_queue_hard_fail_pending_printing_failed(app_db, pending_check):
    main = app_db
    check_id = pending_check

    with main.app.app_context():
        with patch.object(main.cashier_service, "get_shift_status", return_value={"code": 200}):
            with patch.object(
                main.cashier_service,
                "print_check",
                return_value={
                    "code": 500,
                    "message": "registration failed: boom",
                    "error_code": 42,
                    "step": "registration",
                },
            ):
                main.job1()

        check = main.db.session.get(main.Check, check_id)
        assert check is not None
        assert check.status == main.STATUS_FAILED
        assert check.status != main.STATUS_PRINTING
        assert "registration" in (check.error_message or "").lower() or "boom" in (
            check.error_message or ""
        ).lower()
        assert check.isProcessed is not True  # success flags only after print+QR
        # F-DIAG-07: layer mapped from fiscal step when print_check omits layer
        assert check.layer == "KKT"
        assert check.step == "registration"


def test_queue_shift_timeout_requeues_to_pending(app_db, pending_check):
    main = app_db
    check_id = pending_check

    with main.app.app_context():
        with patch.object(
            main,
            "_ensure_shift_ready",
            return_value={
                "code": 504,
                "message": "Shift open timed out after 0.05s",
                "retryable": True,
            },
        ):
            with patch.object(main.cashier_service, "print_check") as mock_print:
                main.job1()
                mock_print.assert_not_called()

        check = main.db.session.get(main.Check, check_id)
        assert check is not None
        assert check.status == main.STATUS_PENDING
        assert check.status != main.STATUS_PRINTING
        assert check.status != main.STATUS_FAILED
        assert "timed out" in (check.error_message or "").lower()
