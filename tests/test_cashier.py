"""Editable cashier settings and ATOL operator login before receipt opening."""

from __future__ import annotations

from html import unescape

import pytest

import conf
from cashierService import FFD_TAG_CASHIER_INN, FFD_TAG_CASHIER_NAME


@pytest.fixture
def isolated_config(tmp_path):
    """Keep cashier tests away from the deployment's instance/config.json."""
    cfg_path = tmp_path / "config.json"
    original_path = conf.CONFIG_PATH
    conf.CONFIG_PATH = cfg_path
    conf.load_config(cfg_path)
    try:
        yield cfg_path
    finally:
        conf.CONFIG_PATH = original_path
        conf.load_config()


def test_cashier_settings_roundtrip_and_module_aliases(isolated_config):
    saved = conf.save_config(
        {
            "cashier_name": "Иванов Иван Иванович, кассир",
            "cashier_inn": "123456789012",
            "send_cashier_to_kkt": False,
        },
        path=isolated_config,
    )

    assert saved["cashier_name"] == "Иванов Иван Иванович, кассир"
    assert saved["cashier_inn"] == "123456789012"
    assert saved["send_cashier_to_kkt"] is False

    conf._config.clear()
    loaded = conf.load_config(isolated_config)

    assert loaded["cashier_name"] == "Иванов Иван Иванович, кассир"
    assert loaded["cashier_inn"] == "123456789012"
    assert loaded["send_cashier_to_kkt"] is False
    assert conf.CASHIER_NAME == loaded["cashier_name"]
    assert conf.CASHIER_INN == loaded["cashier_inn"]
    assert conf.SEND_CASHIER_TO_KKT is False


@pytest.mark.parametrize(
    ("payload", "error_part"),
    [
        ({"cashier_name": "A" * 65}, "cashier_name"),
        ({"cashier_name": "Иванов\nИван"}, "control characters"),
        ({"cashier_name": "Иванов", "cashier_inn": "123"}, "cashier_inn"),
        ({"cashier_name": "Иванов", "cashier_inn": "١٢٣٤٥٦٧٨٩٠١٢"}, "cashier_inn"),
        ({"cashier_name": "", "cashier_inn": "123456789012"}, "required"),
        ({"send_cashier_to_kkt": "maybe"}, "send_cashier_to_kkt"),
    ],
)
def test_cashier_settings_validation(isolated_config, payload, error_part):
    errors = conf.validate_settings_payload(payload)
    assert any(error_part in error for error in errors)


def test_admin_settings_displays_and_persists_cashier(
    isolated_config, app_db
):
    main = app_db
    client = main.app.test_client()

    response = client.post(
        "/admin/settings",
        data={
            "action": "save",
            "cashier_name": "  Петров Пётр, кассир  ",
            "cashier_inn": "123456789012",
            "send_cashier_to_kkt": "0",
        },
    )

    assert response.status_code == 200
    assert conf.get_config()["cashier_name"] == "Петров Пётр, кассир"
    assert conf.get_config()["cashier_inn"] == "123456789012"
    assert conf.get_config()["send_cashier_to_kkt"] is False

    page = unescape(client.get("/admin/settings").get_data(as_text=True))
    assert 'name="cashier_name"' in page
    assert 'value="Петров Пётр, кассир"' in page
    assert 'name="cashier_inn"' in page
    assert 'name="send_cashier_to_kkt"' in page

    status_page = unescape(client.get("/admin/status").get_data(as_text=True))
    assert "Кассир на чеке" in status_page
    assert "Петров Пётр, кассир" in status_page
    assert "Передача программой отключена" in status_page


def test_admin_settings_keeps_disabled_selection_after_validation_error(
    isolated_config, app_db
):
    client = app_db.app.test_client()

    response = client.post(
        "/admin/settings",
        data={
            "action": "save",
            "send_cashier_to_kkt": "0",
            "http_port": "0",
        },
    )

    assert response.status_code == 400
    page = unescape(response.get_data(as_text=True))
    assert '<option value="0" selected>Нет</option>' in page


def test_cashier_change_applies_to_next_receipt_without_reconnect(
    isolated_config, service, flask_logger, sample_check
):
    fptr = service.fptr
    conf.save_config(
        {"cashier_name": "Иванов И.И., кассир", "cashier_inn": "123456789012"},
        path=isolated_config,
    )

    first = service.print_check(sample_check, flask_logger)

    assert first == {"code": 201}
    assert fptr.calls.index("operatorLogin") < fptr.calls.index("openReceipt")
    assert fptr.operator_login_params[-1][FFD_TAG_CASHIER_NAME] == "Иванов И.И., кассир"
    assert fptr.operator_login_params[-1][FFD_TAG_CASHIER_INN] == "123456789012"

    conf.save_config(
        {"cashier_name": "Петров П.П., кассир", "cashier_inn": ""},
        path=isolated_config,
    )
    second = service.print_check(sample_check, flask_logger)

    assert second == {"code": 201}
    assert fptr.operator_login_params[-1][FFD_TAG_CASHIER_NAME] == "Петров П.П., кассир"
    assert FFD_TAG_CASHIER_INN not in fptr.operator_login_params[-1]


def test_operator_login_failure_stops_before_receipt_open(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {"cashier_name": "Иванов И.И., кассир"},
        path=isolated_config,
    )
    fptr = service.fptr
    fptr.fail_next("operatorLogin", code=42, desc="operator login boom")

    result = service.print_check(sample_check, flask_logger)

    assert result["code"] == 500
    assert result["step"] == "operatorLogin"
    assert result["layer"] == "KKT"
    assert "openReceipt" not in fptr.calls
    assert "cancelReceipt" not in fptr.calls


def test_empty_cashier_preserves_existing_kkt_operator(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {"cashier_name": "", "cashier_inn": ""},
        path=isolated_config,
    )

    result = service.print_check(sample_check, flask_logger)

    assert result == {"code": 201}
    assert "operatorLogin" not in service.fptr.calls


def test_disabled_cashier_transmission_skips_operator_login(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {
            "cashier_name": "Иванов И.И., кассир",
            "cashier_inn": "123456789012",
            "send_cashier_to_kkt": False,
        },
        path=isolated_config,
    )

    result = service.print_check(sample_check, flask_logger)

    assert result == {"code": 201}
    assert "operatorLogin" not in service.fptr.calls
    assert service.fptr.operator_login_params == []


def test_automatic_mode_writes_empty_cashier_to_suppress_kkt_fallback(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {
            "automatic_mode": True,
            "machine_number": "00107602314817",
            "cashier_name": "",
            "cashier_inn": "",
            "send_cashier_to_kkt": False,
        },
        path=isolated_config,
    )

    result = service.print_check(sample_check, flask_logger)

    assert result == {"code": 201}
    assert service.fptr.operator_login_params[-1] == {
        FFD_TAG_CASHIER_NAME: ""
    }
    assert service.fptr.calls.index("operatorLogin") < service.fptr.calls.index(
        "openReceipt"
    )
