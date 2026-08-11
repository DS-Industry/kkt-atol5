"""Phase B: soft-retain, id poll, layer mapping, reconnect, health/diagnostics."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from fault_isolation import map_error_to_layer, next_action_for_layer


def test_map_error_to_layer_known_codes():
    assert map_error_to_layer(4) == "LINK"
    assert map_error_to_layer(123) == "FN_OFD"
    assert map_error_to_layer(44) == "KKT"
    assert map_error_to_layer(4, override="APP") == "APP"
    assert map_error_to_layer(None, context="db") == "APP"
    assert map_error_to_layer(99, step="openReceipt") == "KKT"
    assert "USB" in next_action_for_layer("LINK") or "usb" in next_action_for_layer("LINK").lower()


def test_find_actual_check_soft_retains_on_qr(app_db):
    """F-Q-06: QR success must not delete the check row; done/isQr retained."""
    main = app_db
    with main.app.app_context():
        check = main.Check(
            name="Робот 1",
            bay="1",
            type="1",
            sum=100.0,
            status=main.STATUS_DONE,
            isProcessed=True,
            isQr=True,
            qr="t=test&s=100",
        )
        main.db.session.add(check)
        main.db.session.commit()
        check_id = check.id

        with patch.object(main.time, "sleep", return_value=None):
            # Force deadline quickly by using tiny timeout after first poll succeeds
            result = main.find_actual_check("Робот 1", check_id=check_id, timeout_sec=30)

        assert result["code"] == 201
        assert result["qr"] == "t=test&s=100"
        assert result["id"] == check_id
        surviving = main.db.session.get(main.Check, check_id)
        assert surviving is not None
        assert surviving.qr == "t=test&s=100"
        assert surviving.status == main.STATUS_DONE
        assert surviving.isQr is True
        assert surviving.isProcessed is True


def test_id_poll_succeeds_without_name_match(app_db):
    """F-Q-04: id-based wait returns QR for that row even if name differs in query."""
    main = app_db
    with main.app.app_context():
        check = main.Check(
            name="Робот A",
            bay="1",
            type="1",
            sum=75.0,
            status=main.STATUS_DONE,
            isProcessed=True,
            isQr=True,
            qr="t=id-poll&s=75",
        )
        main.db.session.add(check)
        main.db.session.commit()
        check_id = check.id

        with patch.object(main.time, "sleep", return_value=None):
            # Name ignored when check_id is set — wait targets the id
            result = main.find_actual_check(
                "ignored-name", check_id=check_id, timeout_sec=30
            )

        assert result["code"] == 201
        assert result["id"] == check_id
        assert result["qr"] == "t=id-poll&s=75"
        assert main.db.session.get(main.Check, check_id) is not None


def test_find_actual_check_name_poll_ignores_stale_qr(app_db):
    """Name poll must not succeed on soft-retained historical QR for same bay/name."""
    main = app_db
    with main.app.app_context():
        stale = main.Check(
            name="Робот 1",
            bay="1",
            type="1",
            sum=100.0,
            status=main.STATUS_DONE,
            isProcessed=True,
            isQr=True,
            qr="t=stale&s=100",
        )
        main.db.session.add(stale)
        main.db.session.commit()

        # New pending print for same name — name-only wait must target this row
        pending = main.Check(
            name="Робот 1",
            bay="1",
            type="1",
            sum=200.0,
            status=main.STATUS_PENDING,
            isProcessed=False,
            isQr=False,
        )
        main.db.session.add(pending)
        main.db.session.commit()
        pending_id = pending.id

        with patch.object(main.time, "sleep", return_value=None):
            with patch.object(main.time, "monotonic", side_effect=[0.0, 0.0, 9999.0]):
                result = main.find_actual_check("Робот 1", timeout_sec=1)

        assert result["code"] == 504
        assert result["id"] == pending_id
        assert result.get("qr") is None

        # Complete the wait target; id path still soft-retains and returns fresh QR
        pending = main.db.session.get(main.Check, pending_id)
        pending.status = main.STATUS_DONE
        pending.isProcessed = True
        pending.isQr = True
        pending.qr = "t=fresh&s=200"
        main.db.session.commit()

        with patch.object(main.time, "sleep", return_value=None):
            result = main.find_actual_check(
                "Робот 1", check_id=pending_id, timeout_sec=30
            )

        assert result["code"] == 201
        assert result["qr"] == "t=fresh&s=200"
        assert result["id"] == pending_id
        assert main.db.session.get(main.Check, stale.id) is not None

        # Name-only with no pending/printing must not latch onto soft-retained history
        with patch.object(main.time, "sleep", return_value=None):
            with patch.object(main.time, "monotonic", side_effect=[0.0, 0.0, 9999.0]):
                stale_only = main.find_actual_check("Робот 1", timeout_sec=1)
        assert stale_only["code"] == 504
        assert stale_only.get("qr") is None


def test_find_actual_check_timeout_504_includes_id(app_db):
    """F-Q-05: timeout → 504 + check id + status."""
    main = app_db
    with main.app.app_context():
        check = main.Check(
            name="Робот 2",
            bay="2",
            type="1",
            sum=50.0,
            status=main.STATUS_PRINTING,
            isProcessed=False,
            isQr=False,
        )
        main.db.session.add(check)
        main.db.session.commit()
        check_id = check.id

        with patch.object(main.time, "sleep", return_value=None):
            with patch.object(main.time, "monotonic", side_effect=[0.0, 0.0, 9999.0]):
                result = main.find_actual_check("Робот 2", check_id=check_id, timeout_sec=1)

        assert result["code"] == 504
        assert result["id"] == check_id
        assert result["status"] == main.STATUS_PRINTING
        assert result.get("retryable") is True


def test_mark_failed_stores_layer(app_db):
    """F-DIAG-01 / F-DIAG-07: failed checks store layer (+ step)."""
    main = app_db
    with main.app.app_context():
        check = main.Check(
            name="Робот 3",
            bay="3",
            type="1",
            sum=10.0,
            status=main.STATUS_PRINTING,
        )
        main.db.session.add(check)
        main.db.session.commit()

        main._mark_failed(
            check,
            "registration failed: boom",
            42,
            step="registration",
            error_description="boom",
        )
        main.db.session.commit()

        row = main.db.session.get(main.Check, check.id)
        assert row.status == main.STATUS_FAILED
        assert row.layer == "KKT"  # unknown fiscal code at registration → KKT
        assert row.step == "registration"
        assert row.error_code == "42"


def test_ensure_connected_reconnects_with_backoff(service):
    """F-CONN-04: isOpened==0 / error 4 → exponential backoff reconnect."""
    fptr = service.fptr
    fptr._opened = 0
    fptr._fail_once.clear()
    # Fail open twice with error 4, then succeed
    attempts = {"n": 0}

    def flaky_open():
        attempts["n"] += 1
        fptr.calls.append("open")
        if attempts["n"] < 3:
            fptr._error_code = 4
            fptr._error_desc = "Port is not available"
            fptr._opened = 0
            return -1
        fptr._error_code = 0
        fptr._error_desc = ""
        fptr._opened = 1
        return 0

    fptr.open = flaky_open

    with patch("cashierService.time.sleep") as mock_sleep:
        with patch("conf.RECONNECT_BASE_DELAY_SEC", 0.01):
            with patch("conf.RECONNECT_MAX_DELAY_SEC", 0.05):
                result = service.ensure_connected()

    assert result["code"] == 200
    assert result.get("opened") is True
    assert attempts["n"] == 3
    assert mock_sleep.call_count >= 2
    # Backoff grows
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays[0] < delays[-1]


def test_ensure_connected_max_attempts_one(service):
    """Diagnostics/boot: max_attempts=1 does a single open, no backoff ladder."""
    fptr = service.fptr
    fptr._opened = 0
    attempts = {"n": 0}

    def always_fail_open():
        attempts["n"] += 1
        fptr.calls.append("open")
        fptr._error_code = 4
        fptr._error_desc = "Port is not available"
        fptr._opened = 0
        return -1

    fptr.open = always_fail_open

    with patch("cashierService.time.sleep") as mock_sleep:
        result = service.ensure_connected(max_attempts=1)

    assert result["code"] == 500
    assert result.get("opened") is False
    assert result.get("layer") == "LINK"
    assert attempts["n"] == 1
    assert mock_sleep.call_count == 0


def test_get_shift_status_reconnect_false_skips_open(service):
    """/health path: reconnect=False must not call open() when closed."""
    fptr = service.fptr
    fptr._opened = 0
    opens_before = fptr.calls.count("open")

    with patch.object(service, "ensure_connected") as mock_ensure:
        result = service.get_shift_status(reconnect=False)

    mock_ensure.assert_not_called()
    assert result["code"] == 503
    assert result.get("opened") is False
    assert fptr.calls.count("open") == opens_before


def test_get_shift_status_default_uses_ensure_connected(service):
    """Fiscal path: get_shift_status() reconnects when the link is down."""
    service.fptr._opened = 0
    with patch.object(
        service,
        "ensure_connected",
        return_value={"code": 200, "opened": True, "message": "ok"},
    ) as mock_ensure:
        service.fptr._opened = 1
        result = service.get_shift_status()

    mock_ensure.assert_called_once()
    assert result["code"] in (200, 400, 450)


def test_print_check_reconnects_when_closed(service, flask_logger, sample_check):
    """Fiscal print path calls ensure_connected (F-CONN-04) before openReceipt."""
    fptr = service.fptr
    fptr._opened = 0
    fptr.document_closed = True
    fptr.document_printed = True

    attempts = {"n": 0}

    def flaky_open():
        attempts["n"] += 1
        fptr.calls.append("open")
        if attempts["n"] < 2:
            fptr._error_code = 4
            fptr._error_desc = "Port is not available"
            fptr._opened = 0
            return -1
        fptr._error_code = 0
        fptr._error_desc = ""
        fptr._opened = 1
        return 0

    fptr.open = flaky_open

    with patch("cashierService.time.sleep", return_value=None):
        with patch("conf.RECONNECT_BASE_DELAY_SEC", 0.01):
            with patch("conf.RECONNECT_MAX_DELAY_SEC", 0.05):
                result = service.print_check(sample_check, flask_logger)

    assert result == {"code": 201}
    assert attempts["n"] >= 2
    assert "openReceipt" in fptr.calls
    assert fptr.calls.index("open") < fptr.calls.index("openReceipt")


def test_health_and_diagnostics_endpoints(app_db):
    """F-OPS-02 / F-DIAG-05: /health and /admin/diagnostics JSON + matching HTTP code."""
    main = app_db
    client = main.app.test_client()

    with patch.object(
        main.cashier_service,
        "is_device_opened",
        return_value={"code": 200, "opened": True},
    ):
        with patch.object(
            main.cashier_service,
            "get_shift_status",
            return_value={"code": 200, "shift": "OPEN"},
        ) as mock_shift:
            with patch.object(
                main.cashier_service, "ensure_connected"
            ) as mock_ensure:
                resp = client.get("/health")
                assert resp.status_code == 200
                body = resp.get_json()
                assert body["code"] == 200
                assert body["ok"] is True
                assert body["checks"]["db"]["pass"] is True
                assert body["checks"]["device_open"]["pass"] is True
                mock_shift.assert_called_with(reconnect=False)
                mock_ensure.assert_not_called()

    with patch.object(
        main.cashier_service,
        "is_device_opened",
        return_value={"code": 503, "opened": False},
    ):
        with patch.object(
            main.cashier_service, "ensure_connected"
        ) as mock_ensure:
            resp = client.get("/health")
            assert resp.status_code == 503
            body = resp.get_json()
            assert body["code"] == 503
            assert body["ok"] is False
            assert body.get("where") == "LINK" or body.get("layer") == "LINK"
            assert body.get("what_to_do_next")
            mock_ensure.assert_not_called()

    with patch.object(
        main.cashier_service,
        "library_status",
        return_value={"code": 200, "loadable": True},
    ):
        with patch.object(
            main.cashier_service,
            "is_device_opened",
            return_value={"code": 200, "opened": True},
        ):
            with patch.object(
                main.cashier_service,
                "get_shift_status",
                return_value={"code": 200, "shift": "OPEN"},
            ) as mock_diag_shift:
                with patch.object(
                    main.cashier_service,
                    "get_fn_ofd_status",
                    return_value={"code": 200, "fn": {}, "ofd": {}, "errors": {}},
                ) as mock_fn:
                    resp = client.get("/admin/diagnostics")
                    assert resp.status_code == 200
                    body = resp.get_json()
                    assert body["code"] == 200
                    assert body["ok"] is True
                    assert len(body["steps"]) == 5
                    assert all(s["pass"] for s in body["steps"])
                    mock_diag_shift.assert_called_with(reconnect=False)
                    mock_fn.assert_called_with(reconnect=False)


def test_diagnostics_stop_at_first_fail_with_guidance(app_db):
    """F-DIAG-03..05: ladder stops at first fail; returns step + layer + where + next."""
    main = app_db
    client = main.app.test_client()

    with patch.object(
        main.cashier_service,
        "library_status",
        return_value={"code": 200, "loadable": True},
    ):
        with patch.object(
            main.cashier_service,
            "is_device_opened",
            return_value={"code": 503, "opened": False},
        ):
            with patch.object(
                main.cashier_service,
                "ensure_connected",
                return_value={
                    "code": 500,
                    "opened": False,
                    "layer": "LINK",
                    "message": "Device not opened",
                },
            ) as mock_ensure:
                with patch.object(
                    main.cashier_service, "get_shift_status"
                ) as mock_shift:
                    with patch.object(
                        main.cashier_service, "get_fn_ofd_status"
                    ) as mock_fn:
                        resp = client.get("/admin/diagnostics")
                        assert resp.status_code == 503
                        body = resp.get_json()
                        assert body["ok"] is False
                        assert body["failed_step"] == 3
                        assert body["failed_name"] == "open"
                        assert body["layer"] == "LINK"
                        assert body["where"] == "LINK"
                        assert body.get("what_to_do_next")
                        assert "usb" in body["what_to_do_next"].lower() or "USB" in body[
                            "what_to_do_next"
                        ]
                        # Stop-at-first-fail: later ladder steps must not run
                        mock_shift.assert_not_called()
                        mock_fn.assert_not_called()
                        mock_ensure.assert_called_once()
                        kwargs = mock_ensure.call_args.kwargs
                        assert kwargs.get("max_attempts") == 1
                        # Only steps up to and including the failure
                        assert len(body["steps"]) == 3
                        assert body["steps"][-1]["pass"] is False
                        assert body["steps"][-1]["name"] == "open"


def test_job1_hard_fail_persists_layer(app_db):
    """F-DIAG-07: job1 → _mark_failed stores layer from print_check result."""
    main = app_db
    with main.app.app_context():
        check = main.Check(
            name="Робот L",
            bay="7",
            type="1",
            sum=10.0,
            status=main.STATUS_PENDING,
            isProcessed=False,
            isQr=False,
        )
        main.db.session.add(check)
        main.db.session.commit()
        check_id = check.id

    # Fresh context so job1's nested session commit is visible (no stale identity)
    with main.app.app_context():
        with patch.object(
            main.cashier_service, "get_shift_status", return_value={"code": 200}
        ):
            with patch.object(
                main.cashier_service,
                "print_check",
                return_value={
                    "code": 500,
                    "message": "Port unavailable",
                    "error_code": 4,
                    "step": "reconnect",
                    "layer": "LINK",
                    "error_description": "Port is not available",
                },
            ):
                main.job1()

        row = main.db.session.get(main.Check, check_id)
        assert row.status == main.STATUS_FAILED
        assert row.layer == "LINK"
        assert row.step == "reconnect"
        assert row.error_code == "4"


def test_schema_has_phase_b_columns(app_db):
    """Explicit additive columns: layer, step, error_description."""
    main = app_db
    with main.app.app_context():
        main._ensure_schema()
        from sqlalchemy import inspect

        cols = {c["name"] for c in inspect(main.db.engine).get_columns("check")}
        assert "layer" in cols
        assert "step" in cols
        assert "error_description" in cols
        # Legacy typo/contract fields must remain (not renamed)
        assert "isProcessed" in cols
