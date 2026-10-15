import json
from unittest.mock import patch

import pytest

import conf
import fiscal_report


SNAPSHOT = {
    "treasurerLinkOpen": True,
    "shiftStatus": "OPEN",
    "fnMemoryOverflow": False,
    "fnResourceExhausted": False,
    "fnReplacementRequired": True,
    "ofdUnsentDocumentsCount": 4,
}

RECEIPT = {
    "documentTLV": {
        "1012": "2026-01-02T03:04:00",
        "qr": "t=20260101T120000&s=100.00&fn=1&i=1&fp=1&n=1",
    }
}


@pytest.fixture
def isolated_config(tmp_path):
    cfg_path = tmp_path / "config.json"
    original_path = conf.CONFIG_PATH
    conf.CONFIG_PATH = cfg_path
    conf.load_config(cfg_path)
    try:
        yield cfg_path
    finally:
        conf.CONFIG_PATH = original_path
        conf.load_config()


def _check_view(**overrides):
    view = {
        "status": "done",
        "name": "Пост 2",
        "type": "0",
        "sum": 150.0,
        "qr": RECEIPT["documentTLV"]["qr"],
        "fiscal_document": json.dumps(RECEIPT),
        "step": None,
        "error_code": None,
        "error_text": None,
    }
    view.update(overrides)
    return view


def test_success_packet_uses_tag_1012_and_cash_label():
    packet, missing = fiscal_report.build_packet(_check_view(), SNAPSHOT, 15)
    assert missing == []
    assert packet["posId"] == 15
    assert packet["operationTime"] == "2026-01-02T03:04:00"
    assert packet["amount"] == 150
    assert packet["deviceName"] == "Пост 2"
    assert packet["paymentType"] == "Наличные"
    assert packet["qr"] == RECEIPT["documentTLV"]["qr"]
    assert packet["state"]["receiptAttemptSucceeded"] is True
    assert packet["state"]["fnReplacementRequired"] is True
    assert packet["state"]["ofdUnsentDocumentsCount"] == 4


def test_operation_time_falls_back_to_qr_minute_precision():
    assert (
        fiscal_report.operation_time(None, "t=20260102T0304&s=1")
        == "2026-01-02T03:04:00"
    )


def test_failed_packet_has_state_only():
    packet, missing = fiscal_report.build_packet(
        _check_view(
            status="failed",
            step="registration",
            error_code="42",
            error_text="нет связи",
        ),
        SNAPSHOT,
        15,
    )
    assert missing == []
    assert set(packet) == {"posId", "state"}
    assert packet["state"]["receiptAttemptSucceeded"] is False
    assert packet["state"]["driverErrorCode"] == 42
    assert packet["state"]["driverErrorStep"] == "registration"
    assert packet["state"]["driverErrorText"] == "нет связи"


def test_packet_is_not_built_when_fn_replacement_is_missing():
    snapshot = dict(SNAPSHOT)
    snapshot["fnReplacementRequired"] = None
    packet, missing = fiscal_report.build_packet(_check_view(), snapshot, 15)
    assert packet is None
    assert missing == ["fnReplacementRequired"]


def test_cashless_label_for_nonzero_type():
    packet, missing = fiscal_report.build_packet(
        _check_view(type="1"), SNAPSHOT, 15
    )
    assert missing == []
    assert packet["paymentType"] == "Безналичные"


def _enable_monitoring(isolated_config):
    conf.save_config(
        {
            "monitoring_url": "https://monitor.example",
            "monitoring_pos_id": 15,
            "monitoring_api_key": "org-secret",
        },
        path=isolated_config,
    )


def _pending(main, **overrides):
    fields = dict(
        name="Пост 2",
        bay="2",
        type="0",
        sum=150.0,
        status=main.STATUS_PENDING,
        isProcessed=False,
        isQr=False,
    )
    fields.update(overrides)
    check = main.Check(**fields)
    main.db.session.add(check)
    main.db.session.commit()
    return check.id


def test_create_check_400_does_not_queue(app_db, isolated_config):
    main = app_db
    _enable_monitoring(isolated_config)
    client = main.app.test_client()
    with main.app.app_context():
        response = client.post("/create-check")
        assert response.status_code == 400
        assert main.FiscalOutbox.query.count() == 0


def test_http_failure_keeps_done_check_and_outbox(app_db, isolated_config):
    main = app_db
    _enable_monitoring(isolated_config)
    check_id = None
    with main.app.app_context():
        check_id = _pending(main)
        receipt = json.dumps(RECEIPT)
        with patch.object(
            main.cashier_service, "get_shift_status", return_value={"code": 200}
        ):
            with patch.object(
                main.cashier_service, "print_check", return_value={"code": 201}
            ):
                with patch.object(
                    main.cashier_service, "readLastReciept", return_value=receipt
                ):
                    with patch.object(main, "_device_snapshot", return_value=SNAPSHOT):
                        main.job1()
        check = main.db.session.get(main.Check, check_id)
        assert check.status == main.STATUS_DONE
        assert check.qr == RECEIPT["documentTLV"]["qr"]
        assert main.FiscalOutbox.query.count() == 1
        with patch("fiscal_report.deliver", return_value=False):
            main.flush_fiscal_outbox()
        check = main.db.session.get(main.Check, check_id)
        assert check.status == main.STATUS_DONE
        assert main.FiscalOutbox.query.count() == 1


def test_requeue_does_not_queue_monitor_packet(app_db, isolated_config):
    main = app_db
    _enable_monitoring(isolated_config)
    with main.app.app_context():
        check_id = _pending(main)
        with patch.object(
            main,
            "_ensure_shift_ready",
            return_value={"code": 504, "message": "Shift open timed out", "retryable": True},
        ):
            main.job1()
        check = main.db.session.get(main.Check, check_id)
        assert check.status == main.STATUS_PENDING
        assert main.FiscalOutbox.query.count() == 0


def test_outbox_retries_in_order_until_accepted(app_db, isolated_config):
    main = app_db
    _enable_monitoring(isolated_config)
    sent = []

    def deliver(base_url, api_key, body, timeout=5):
        sent.append((base_url, api_key, body["state"]["driverErrorText"]))
        return len(sent) > 1

    with main.app.app_context():
        main.db.session.add(
            main.FiscalOutbox(
                check_id=1,
                payload=json.dumps(
                    {"posId": 15, "state": {"driverErrorText": "older"}}
                ),
            )
        )
        main.db.session.add(
            main.FiscalOutbox(
                check_id=2,
                payload=json.dumps(
                    {"posId": 15, "state": {"driverErrorText": "newer"}}
                ),
            )
        )
        main.db.session.commit()
        with patch("fiscal_report.deliver", side_effect=deliver):
            main.flush_fiscal_outbox()
            assert [item[2] for item in sent] == ["older"]
            assert main.FiscalOutbox.query.count() == 2
            main.flush_fiscal_outbox()
        assert [item[2] for item in sent] == ["older", "older", "newer"]
        assert sent[0][0] == "https://monitor.example"
        assert sent[0][1] == "org-secret"
        assert main.FiscalOutbox.query.count() == 0


def test_settings_page_shows_url_and_pos_id_without_api_key(app_db, isolated_config):
    main = app_db
    _enable_monitoring(isolated_config)
    client = main.app.test_client()
    page = client.get("/admin/settings").get_data(as_text=True)
    assert 'id="monitoring_url"' in page
    assert 'value="https://monitor.example"' in page
    assert 'id="monitoring_pos_id"' in page
    assert 'value="15"' in page
    assert "org-secret" not in page
    assert "monitoring_api_key" not in page

    response = client.post(
        "/admin/settings",
        data={
            "action": "save",
            "connection_mode": "usb",
            "monitoring_url": "https://monitor.example/data/fiscal",
            "monitoring_pos_id": "16",
            "monitoring_api_key": "replaced-secret",
            "kkt_ip": "",
            "kkt_tcp_port": "5555",
            "library_path": "/usr/lib/",
            "cashier_name": "",
            "cashier_inn": "",
            "send_cashier_to_kkt": "1",
            "automatic_mode": "0",
            "machine_number": "",
            "machine_numbers_by_bay": "",
            "tax_type": "no_vat",
            "http_host": "0.0.0.0",
            "http_port": "5000",
            "qr_wait_timeout_sec": "180",
            "shift_open_timeout_sec": "120",
            "log_path": "atol.log",
            "max_log_lines": "300",
        },
    )
    assert response.status_code == 200
    saved = conf.get_config()
    assert saved["monitoring_url"] == "https://monitor.example"
    assert saved["monitoring_pos_id"] == 16
    assert saved["monitoring_api_key"] == "org-secret"
    assert "org-secret" not in response.get_data(as_text=True)
    assert "replaced-secret" not in response.get_data(as_text=True)
