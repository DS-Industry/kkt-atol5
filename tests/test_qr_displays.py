from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import socket
import threading
from unittest.mock import patch

import pytest

import conf
import qr_displays as screens


@pytest.fixture
def display_config(tmp_path, monkeypatch):
    original = conf.get_config()
    monkeypatch.setattr(conf, "CONFIG_PATH", tmp_path / "config.json")
    conf.load_config()
    yield
    conf._config = original
    conf._sync_module_attrs(original)


def configure(**ips):
    counts = {key: 1 for key, _, _ in screens.GROUPS}
    cfg, errors = screens.save_counts({}, counts)
    assert not errors
    cfg, errors = screens.save_addresses(cfg, {
        key: {"1": {"ip": ip, "port": 5000}} for key, ip in ips.items()
    })
    assert not errors
    conf.save_config({"qr_displays": cfg})
    return cfg


@contextmanager
def display_server(identity=True, echo=True):
    frames, failures = [], []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)

    def serve():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(3)
                stream = conn.makefile("rb")
                first = stream.readline()
                frames.append(first)
                conn.sendall(b"\r\nhttp://telemetron.ru/\r\nhw=1.3.0;\r\nswm=2.4;\r\n" if identity else b"Other device\n")
                if identity:
                    second = stream.readline()
                    if second:
                        frames.append(second)
                        conn.sendall(b"rb1[" + str(len(second) - 1).encode() + b"]=" + second if echo else b"qr=error\n")
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield listener.getsockname()[1], frames
    finally:
        worker.join(5)
        listener.close()
        assert not worker.is_alive()
        assert not failures


def test_real_tcp_roundtrip_and_exact_payload():
    with display_server() as (port, frames):
        info = screens.communicate("127.0.0.1", port, "https://example.com/pay?a=1&b=2")
    assert "swm=2.4" in info
    assert frames == [b"info\n", b"qr=https://example.com/pay?a=1&b=2\n"]


def test_transport_refuses_unknown_identity_before_qr():
    with display_server(identity=False) as (port, frames):
        with pytest.raises(OSError, match="Telemetron"):
            screens.communicate("127.0.0.1", port, "hello")
    assert frames == [b"info\n"]


def test_transport_rejects_error_instead_of_success():
    with display_server(echo=False) as (port, frames):
        with pytest.raises(OSError):
            screens.communicate("127.0.0.1", port, "hello")


def test_connect_error_names_the_screen():
    with patch.object(socket, "create_connection", side_effect=TimeoutError()):
        with pytest.raises(OSError, match="192.168.28.201:5000"):
            screens.communicate("192.168.28.201", 5000)


@pytest.mark.parametrize("data", ["", "a\nimg=1", "a" * 201, "😀", "a\t", "a\x7f"])
def test_invalid_qr_never_connects(data):
    with patch.object(socket, "create_connection") as connect:
        with pytest.raises(ValueError):
            screens.communicate("192.168.28.201", 5000, data)
    connect.assert_not_called()


@pytest.mark.parametrize("count", [-1, 101, True, 1.5, "9" * 5000])
def test_invalid_counts(count):
    _, errors = screens.save_counts({}, {"wash": count})
    assert errors


def test_admin_counts_then_addresses_and_restart_persistence(app_db, display_config):
    client = app_db.app.test_client()
    result = client.post("/admin/displays", data={"action": "save_counts", "count_wash": "2", "count_robot": "1", "count_vacuum": "1"}, follow_redirects=True)
    assert result.status_code == 200
    for field in (b"ip_wash_1", b"ip_wash_2", b"ip_robot_1", b"ip_vacuum_1"):
        assert field in result.data
    assert b"ip_wash_3" not in result.data
    result = client.post("/admin/displays", json={"action": "save_addresses", "screens": {
        "wash": {"1": {"ip": "192.168.28.201", "port": 5000}, "2": {"ip": "192.168.28.202", "port": 5000}},
        "robot": {"1": {"ip": "192.168.28.210", "port": 5000}},
        "vacuum": {"1": {"ip": "192.168.28.220", "port": 5000}},
    }})
    assert result.status_code == 200
    conf.load_config()
    assert screens.endpoint(conf.get_config()["qr_displays"], "wash", "1") == ("192.168.28.201", 5000)
    assert screens.endpoint(conf.get_config()["qr_displays"], "robot", "1") == ("192.168.28.210", 5000)
    assert screens.endpoint(conf.get_config()["qr_displays"], "vacuum", "1") == ("192.168.28.220", 5000)


@pytest.mark.parametrize("entry", [{"ip": "http://192.168.28.201"}, {"ip": "abc"}, {"ip": "0.0.0.0"}, {"ip": "224.0.0.1"}, {"ip": "192.168.28.201", "port": 65536}, {"ip": "192.168.28.201", "port": True}])
def test_invalid_address_not_saved(app_db, display_config, entry):
    configure(wash="192.168.28.201")
    before = conf.get_config()
    result = app_db.app.test_client().post("/admin/displays", json={"action": "save_addresses", "screens": {"wash": {"1": entry}}})
    assert result.status_code == 400
    assert conf.get_config() == before


def test_duplicate_screen_across_categories_rejected(app_db, display_config):
    configure(wash="192.168.28.201")
    result = app_db.app.test_client().post("/admin/displays", json={"action": "save_addresses", "screens": {"robot": {"1": {"ip": "192.168.28.201", "port": 5000}}}})
    assert result.status_code == 400
    assert screens.endpoint(conf.get_config()["qr_displays"], "robot", "1") is None


def test_reenabling_preserved_duplicate_is_rejected(app_db, display_config):
    configure(wash="192.168.28.201")
    client = app_db.app.test_client()
    assert client.post("/admin/displays", json={"action": "save_counts", "counts": {"wash": 0}}).status_code == 200
    assert client.post("/admin/displays", json={"action": "save_addresses", "screens": {"robot": {"1": {"ip": "192.168.28.201"}}}}).status_code == 200
    assert client.post("/admin/displays", json={"action": "save_counts", "counts": {"wash": 1}}).status_code == 400
    assert conf.get_config()["qr_displays"]["wash"]["count"] == 0


def test_failed_save_keeps_previous_mapping(app_db, display_config):
    configure(wash="192.168.28.201")
    before = conf.get_config()
    with patch.object(app_db, "save_config", side_effect=OSError("disk full")):
        result = app_db.app.test_client().post("/admin/displays", json={"action": "save_addresses", "screens": {"wash": {"1": {"ip": "192.168.28.202"}}}})
    assert result.status_code == 500
    assert conf.get_config() == before


def create_done(main, name="Пост 1", bay="1", qr="t=20261014T1200&s=100.00&fn=1&i=1&fp=1&n=1"):
    check = main.Check(name=name, bay=bay, type="1", sum=100, status="done", isProcessed=True, isQr=True, qr=qr)
    main.db.session.add(check)
    main.db.session.commit()
    main._queue_qr_display(check)
    return check


def test_live_address_change_used_for_already_waiting_delivery(app_db, display_config):
    main = app_db
    configure(wash="192.168.28.201")
    with main.app.app_context():
        check = create_done(main)
        result = main.app.test_client().post("/admin/displays", json={"action": "save_addresses", "screens": {"wash": {"1": {"ip": "192.168.28.202", "port": 5001}}}})
        assert result.status_code == 200
        with patch.object(screens, "communicate") as send:
            main.flush_qr_displays()
        send.assert_called_once_with("192.168.28.202", 5001, check.qr)
        assert main.QRDisplayDelivery.query.one().status == "sent"


def test_same_bay_different_groups_never_share_mapping(app_db, display_config):
    main = app_db
    configure(wash="192.168.28.201", robot="192.168.28.210", vacuum="192.168.28.220")
    with main.app.app_context():
        for label in ("Пост", "Робот", "Пылесос"):
            create_done(main, name=f"{label} 1", qr=label)
        with patch.object(screens, "communicate") as send:
            main.flush_qr_displays()
        assert [call.args[0] for call in send.call_args_list] == ["192.168.28.201", "192.168.28.210", "192.168.28.220"]


def test_new_receipt_supersedes_old_retry(app_db, display_config):
    main = app_db
    configure(wash="192.168.28.201")
    with main.app.app_context():
        old = create_done(main, qr="old")
        new = create_done(main, qr="new")
        with patch.object(screens, "communicate") as send:
            main.flush_qr_displays()
        send.assert_called_once_with("192.168.28.201", 5000, "new")
        assert main.QRDisplayDelivery.query.filter_by(check_id=old.id).one().status == "superseded"
        assert main.QRDisplayDelivery.query.filter_by(check_id=new.id).one().status == "sent"


def test_disabled_screen_skips_waiting_delivery_and_remembers_address(app_db, display_config):
    main = app_db
    configure(wash="192.168.28.201")
    with main.app.app_context():
        create_done(main)
        response = main.app.test_client().post("/admin/displays", json={"action": "save_counts", "counts": {"wash": 0}})
        assert response.status_code == 200
        with patch.object(screens, "communicate") as send:
            main.flush_qr_displays()
        send.assert_not_called()
        assert main.QRDisplayDelivery.query.one().status == "skipped"
        assert conf.get_config()["qr_displays"]["wash"]["screens"]["1"]["ip"] == "192.168.28.201"


def test_display_failure_does_not_change_fiscal_success_or_reprint(app_db, display_config):
    main = app_db
    configure(wash="192.168.28.201")
    with main.app.app_context():
        check = main.Check(name="Пост 1", bay="1", type="1", sum=100, status="pending")
        main.db.session.add(check)
        main.db.session.commit()
        result = json.dumps({"documentTLV": {"qr": "test-qr"}})
        with patch.object(main, "_ensure_shift_ready", return_value={"code": 200}), patch.object(main.cashier_service, "print_check", return_value={"code": 201}) as printing, patch.object(main.cashier_service, "readLastReciept", return_value=result), patch.object(screens, "communicate", side_effect=TimeoutError("screen offline")) as send:
            main.job1()
            assert main.QRDisplayDelivery.query.one().status == "pending"
            for _ in range(3):
                row = main.QRDisplayDelivery.query.one()
                row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
                main.db.session.commit()
                main.flush_qr_displays()
            main.job1()
        assert printing.call_count == 1
        assert send.call_count == 3
        assert check.status == "done" and check.isProcessed and check.isQr
        assert main.QRDisplayDelivery.query.one().status == "failed"


def test_fiscal_failure_never_sends_qr(app_db, display_config):
    main = app_db
    configure(wash="192.168.28.201")
    with main.app.app_context():
        check = main.Check(name="Пост 1", bay="1", type="1", sum=100, status="failed", qr="old")
        main.db.session.add(check)
        main.db.session.commit()
        main._queue_qr_display(check)
        assert main.QRDisplayDelivery.query.count() == 0


def test_test_button_uses_saved_endpoint_and_never_fiscalizes(app_db, display_config):
    configure(wash="192.168.28.201")
    with patch.object(screens, "communicate", return_value="hw=1.3.0;") as send, patch.object(app_db.cashier_service, "print_check") as printing:
        result = app_db.app.test_client().post("/admin/displays/test?show_qr=1", json={"target": "wash:1", "ip_wash_1": "192.168.28.222"})
    assert result.status_code == 200
    send.assert_called_once_with("192.168.28.201", 5000, "https://example.com/telemetron-test")
    printing.assert_not_called()


def test_history_is_bounded_independently_of_check_pruning(app_db, display_config):
    main = app_db
    with main.app.app_context():
        main.db.session.add_all([main.QRDisplayDelivery(check_id=i, category="wash", bay="1", qr="x", status="sent") for i in range(1, 1004)])
        main.db.session.commit()
        main.flush_qr_displays()
        assert main.QRDisplayDelivery.query.count() == 1000
