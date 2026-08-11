"""Phase C: config persistence, USB|TCP driver settings, Admin GUI save/screens."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from libfptr10 import IFptr

import conf


@pytest.fixture
def isolated_config(tmp_path):
    """
    Point conf at a temp config.json and reset in-memory state to defaults.
    Restores real CONFIG_PATH + reload after the test (do not touch production file).
    """
    cfg_path = tmp_path / "config.json"
    original_path = conf.CONFIG_PATH
    conf.CONFIG_PATH = cfg_path
    conf.load_config(cfg_path)  # missing → defaults
    try:
        yield cfg_path
    finally:
        conf.CONFIG_PATH = original_path
        conf.load_config()


# ---------------------------------------------------------------------------
# 1. Config persistence (F-CFG-01–04)
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_defaults(isolated_config):
    """Missing config.json → shipped defaults; app-usable."""
    assert not isolated_config.exists()
    cfg = conf.get_config()
    assert cfg["connection_mode"] == "usb"
    assert cfg["kkt_ip"] == ""
    assert cfg["kkt_tcp_port"] == 5555
    assert cfg["http_host"] == "0.0.0.0"
    assert cfg["http_port"] == 5000
    assert cfg["library_path"] == "/usr/lib/"
    assert cfg["qr_wait_timeout_sec"] == 180
    assert cfg["shift_open_timeout_sec"] == 120
    assert cfg["log_path"] == "atol.log"
    assert cfg["max_log_lines"] == 300


def test_save_load_roundtrip_mode_ip_port_and_fcfg02(isolated_config):
    """save_config → load_config preserves USB/TCP + F-CFG-02 Settings fields."""
    updates = {
        "connection_mode": "tcp",
        "kkt_ip": "192.168.10.20",
        "kkt_tcp_port": 7777,
        "library_path": "/opt/atol/",
        "http_host": "127.0.0.1",
        "http_port": 5050,
        "qr_wait_timeout_sec": 90,
        "shift_open_timeout_sec": 60,
        "log_path": "custom-atol.log",
        "max_log_lines": 150,
    }
    saved = conf.save_config(updates, path=isolated_config)
    for key, value in updates.items():
        assert saved[key] == value
    assert isolated_config.is_file()

    conf._config.clear()
    loaded = conf.load_config(isolated_config)
    for key, value in updates.items():
        assert loaded[key] == value
    assert conf.CONNECTION_MODE == "tcp"
    assert conf.KKT_IP == "192.168.10.20"
    assert conf.KKT_TCP_PORT == 7777


def test_validate_settings_rejects_invalid_payloads(isolated_config):
    """Invalid mode / port / TCP-without-IP → validation errors."""
    assert conf.validate_settings_payload({"connection_mode": "serial"})
    assert any("connection_mode" in e for e in conf.validate_settings_payload({"connection_mode": "wifi"}))

    port_errs = conf.validate_settings_payload({"kkt_tcp_port": 99999})
    assert any("kkt_tcp_port" in e for e in port_errs)

    http_errs = conf.validate_settings_payload({"http_port": 0})
    assert any("http_port" in e for e in http_errs)

    tcp_errs = conf.validate_settings_payload(
        {"connection_mode": "tcp", "kkt_ip": "  "}
    )
    assert any("kkt_ip" in e for e in tcp_errs)

    ok = conf.validate_settings_payload(
        {
            "connection_mode": "tcp",
            "kkt_ip": "10.0.0.5",
            "kkt_tcp_port": 5555,
        }
    )
    assert ok == []


def test_admin_settings_invalid_returns_400(app_db, isolated_config):
    """POST /admin/settings with bad payload → HTTP 400 + errors."""
    main = app_db
    client = main.app.test_client()
    resp = client.post(
        "/admin/settings",
        json={"connection_mode": "tcp", "kkt_ip": "", "kkt_tcp_port": 5555},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == 400
    assert body.get("errors")
    assert any("kkt_ip" in e for e in body["errors"])


# ---------------------------------------------------------------------------
# 2–3. USB vs TCP apply + reconnect uses config
# ---------------------------------------------------------------------------


def test_apply_port_settings_usb(service, isolated_config):
    """USB mode: Port=USB; no IPAddress/IPPort; applySingleSettings called."""
    conf.save_config({"connection_mode": "usb"}, path=isolated_config)
    fptr = service.fptr
    fptr._settings = {}
    fptr.calls.clear()

    ok, err = service._apply_port_settings()
    assert ok is True
    assert err is None
    assert fptr._settings[IFptr.LIBFPTR_SETTING_PORT] == str(IFptr.LIBFPTR_PORT_USB)
    assert IFptr.LIBFPTR_SETTING_IPADDRESS not in fptr._settings
    assert IFptr.LIBFPTR_SETTING_IPPORT not in fptr._settings
    assert "applySingleSettings" in fptr.calls


def test_apply_port_settings_tcp(service, isolated_config):
    """TCP mode: Port=TCPIP + IPAddress + IPPort from conf."""
    conf.save_config(
        {
            "connection_mode": "tcp",
            "kkt_ip": "192.168.1.50",
            "kkt_tcp_port": 5555,
        },
        path=isolated_config,
    )
    fptr = service.fptr
    fptr._settings = {}
    fptr.calls.clear()

    ok, err = service._apply_port_settings()
    assert ok is True
    assert err is None
    assert fptr._settings[IFptr.LIBFPTR_SETTING_PORT] == str(IFptr.LIBFPTR_PORT_TCPIP)
    assert fptr._settings[IFptr.LIBFPTR_SETTING_IPADDRESS] == "192.168.1.50"
    assert fptr._settings[IFptr.LIBFPTR_SETTING_IPPORT] == "5555"
    assert "applySingleSettings" in fptr.calls


def test_apply_settings_and_reconnect_applies_tcp_then_opens(
    service, isolated_config
):
    """apply_settings_and_reconnect re-reads conf, applies TCP settings, opens."""
    conf.save_config(
        {
            "connection_mode": "tcp",
            "kkt_ip": "10.1.2.3",
            "kkt_tcp_port": 6000,
        },
        path=isolated_config,
    )
    fptr = service.fptr
    fptr._opened = 0
    fptr._settings = {}
    fptr.calls.clear()

    with patch("cashierService.time.sleep", return_value=None):
        with patch("conf.RECONNECT_BASE_DELAY_SEC", 0.01):
            with patch("conf.RECONNECT_MAX_DELAY_SEC", 0.05):
                result = service.apply_settings_and_reconnect(max_attempts=1)

    assert result["code"] == 200
    assert result.get("opened") is True
    assert fptr._settings[IFptr.LIBFPTR_SETTING_PORT] == str(IFptr.LIBFPTR_PORT_TCPIP)
    assert fptr._settings[IFptr.LIBFPTR_SETTING_IPADDRESS] == "10.1.2.3"
    assert fptr._settings[IFptr.LIBFPTR_SETTING_IPPORT] == "6000"
    assert "applySingleSettings" in fptr.calls
    assert "open" in fptr.calls
    assert fptr.calls.index("applySingleSettings") < fptr.calls.index("open")


def test_apply_settings_and_reconnect_switches_usb_to_tcp(
    service, isolated_config
):
    """Mode switch: USB settings first, then TCP after save + reconnect."""
    conf.save_config({"connection_mode": "usb"}, path=isolated_config)
    ok, _ = service._apply_port_settings()
    assert ok
    assert service.fptr._settings[IFptr.LIBFPTR_SETTING_PORT] == str(
        IFptr.LIBFPTR_PORT_USB
    )

    conf.save_config(
        {
            "connection_mode": "tcp",
            "kkt_ip": "172.16.0.9",
            "kkt_tcp_port": 5555,
        },
        path=isolated_config,
    )
    service.fptr._opened = 0
    with patch("cashierService.time.sleep", return_value=None):
        with patch("conf.RECONNECT_MAX_ATTEMPTS", 1):
            result = service.apply_settings_and_reconnect(max_attempts=1)

    assert result["code"] == 200
    assert service.fptr._settings[IFptr.LIBFPTR_SETTING_PORT] == str(
        IFptr.LIBFPTR_PORT_TCPIP
    )
    assert service.fptr._settings[IFptr.LIBFPTR_SETTING_IPADDRESS] == "172.16.0.9"


# ---------------------------------------------------------------------------
# 4. Admin GUI save (JSON + form) + save_reconnect
# ---------------------------------------------------------------------------


def test_admin_settings_json_persists(app_db, isolated_config):
    """POST /admin/settings JSON saves mode/IP/port to config file + memory."""
    main = app_db
    client = main.app.test_client()
    resp = client.post(
        "/admin/settings",
        json={
            "action": "save",
            "connection_mode": "tcp",
            "kkt_ip": "192.168.0.40",
            "kkt_tcp_port": 5555,
            "http_port": 5000,
            "qr_wait_timeout_sec": 120,
        },
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 200
    assert body["config"]["connection_mode"] == "tcp"
    assert body["config"]["kkt_ip"] == "192.168.0.40"
    assert conf.get_config()["kkt_ip"] == "192.168.0.40"
    assert isolated_config.is_file()


def test_admin_settings_form_persists(app_db, isolated_config):
    """POST /admin/settings form fields persist like JSON."""
    main = app_db
    client = main.app.test_client()
    resp = client.post(
        "/admin/settings",
        data={
            "action": "save",
            "connection_mode": "usb",
            "kkt_ip": "",
            "kkt_tcp_port": "5555",
            "http_host": "0.0.0.0",
            "http_port": "5000",
            "library_path": "/usr/lib/",
            "qr_wait_timeout_sec": "180",
            "shift_open_timeout_sec": "120",
            "log_path": "atol.log",
            "max_log_lines": "300",
        },
    )
    assert resp.status_code == 200
    assert conf.get_config()["connection_mode"] == "usb"
    assert isolated_config.is_file()


def test_admin_settings_save_reconnect_invokes_service(app_db, isolated_config):
    """action=save_reconnect persists then calls apply_settings_and_reconnect."""
    main = app_db
    client = main.app.test_client()
    with patch.object(
        main.cashier_service,
        "apply_settings_and_reconnect",
        return_value={"code": 200, "opened": True, "message": "Connection open"},
    ) as mock_reconnect:
        resp = client.post(
            "/admin/settings",
            json={
                "action": "save_reconnect",
                "connection_mode": "tcp",
                "kkt_ip": "10.0.0.8",
                "kkt_tcp_port": 5555,
            },
            headers={"Accept": "application/json"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["config"]["connection_mode"] == "tcp"
    assert body["config"]["kkt_ip"] == "10.0.0.8"
    mock_reconnect.assert_called_once()
    assert "reconnect" in body


def test_admin_reconnect_endpoint_invokes_service(app_db, isolated_config):
    """POST /admin/reconnect uses apply_settings_and_reconnect."""
    main = app_db
    client = main.app.test_client()
    with patch.object(
        main.cashier_service,
        "apply_settings_and_reconnect",
        return_value={"code": 200, "opened": True, "message": "Connection open"},
    ) as mock_reconnect:
        resp = client.post(
            "/admin/reconnect",
            headers={"Accept": "application/json"},
        )

    assert resp.status_code == 200
    mock_reconnect.assert_called_once()
    assert resp.get_json().get("opened") is True


# ---------------------------------------------------------------------------
# 5. Admin screens A–D return HTML 200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/admin", "/admin/status", "/admin/settings", "/admin/logs", "/admin/checks"],
)
def test_admin_screens_return_html_200(app_db, isolated_config, path):
    """Screens A–D: GET returns 200 HTML (LAN MVP, no auth)."""
    main = app_db
    client = main.app.test_client()
    # Status page may touch device — stub shift/open to keep HTML render stable
    with patch.object(
        main.cashier_service,
        "is_device_opened",
        return_value={"code": 200, "opened": True},
    ):
        with patch.object(
            main.cashier_service,
            "get_shift_status",
            return_value={"code": 200, "shift": "OPEN"},
        ):
            with patch.object(
                main.cashier_service,
                "connection_info",
                return_value={
                    "connection_mode": "usb",
                    "kkt_ip": "",
                    "kkt_tcp_port": 5555,
                    "library_path": "/usr/lib/",
                    "busy": False,
                },
            ):
                resp = client.get(path)

    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert b"<html" in resp.data.lower() or b"<!doctype" in resp.data.lower()
