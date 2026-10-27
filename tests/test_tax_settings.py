"""Admin-configured ATOL tax rate and receipt tax calculation."""

from __future__ import annotations

from html import unescape

import pytest

import app.data.config as conf
from app.services.cashier import TAX_DRIVER_TYPES
from libfptr10 import IFptr


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


def test_tax_setting_is_validated_persisted_and_shown(
    isolated_config, app_db
):
    client = app_db.app.test_client()

    assert conf.get_config()["tax_type"] == "no_vat"
    assert conf.validate_settings_payload({"tax_type": "vat7"}) == []
    assert conf.validate_settings_payload({"tax_type": "vat20"})

    response = client.post(
        "/admin/settings",
        data={"action": "save", "tax_type": "vat7"},
    )

    assert response.status_code == 200
    assert conf.get_config()["tax_type"] == "vat7"
    page = unescape(client.get("/admin/settings").get_data(as_text=True))
    assert 'name="tax_type"' in page
    assert 'value="vat7" selected' in page
    status = unescape(client.get("/admin/status").get_data(as_text=True))
    assert "Налоговая ставка" in status
    assert "НДС 7%" in status


@pytest.mark.parametrize(
    ("tax_type", "driver_value", "tax_sum"),
    [
        ("no_vat", 6, 122.00),
        ("vat0", 5, 122.00),
        ("vat5", 9, 5.81),
        ("vat7", 10, 7.98),
        ("vat10", 2, 11.09),
        ("vat22", 13, 22.00),
    ],
)
def test_tax_mapping_and_sum_on_item_and_receipt(
    isolated_config,
    service,
    flask_logger,
    sample_check,
    tax_type,
    driver_value,
    tax_sum,
):
    conf.save_config({"tax_type": tax_type}, path=isolated_config)
    sample_check = {**sample_check, "price": 122.0, "sum": 122.0}

    result = service.print_check(sample_check, flask_logger)

    assert result == {"code": 201}
    assert TAX_DRIVER_TYPES[tax_type] == driver_value
    assert (
        service.fptr.registration_params[-1][IFptr.LIBFPTR_PARAM_TAX_TYPE]
        == driver_value
    )
    receipt_tax = service.fptr.receipt_tax_params[-1]
    assert receipt_tax[IFptr.LIBFPTR_PARAM_TAX_TYPE] == driver_value
    assert receipt_tax[IFptr.LIBFPTR_PARAM_TAX_SUM] == tax_sum
    assert isinstance(receipt_tax[IFptr.LIBFPTR_PARAM_TAX_SUM], float)


def test_tax_change_applies_to_next_receipt_without_reconnect(
    isolated_config, service, flask_logger, sample_check
):
    fptr = service.fptr
    fptr.calls.clear()
    conf.save_config({"tax_type": "no_vat"}, path=isolated_config)
    assert service.print_check(sample_check, flask_logger) == {"code": 201}

    conf.save_config({"tax_type": "vat22"}, path=isolated_config)
    assert service.print_check(sample_check, flask_logger) == {"code": 201}

    assert "open" not in fptr.calls
    assert [
        params[IFptr.LIBFPTR_PARAM_TAX_TYPE]
        for params in fptr.receipt_tax_params[-2:]
    ] == [6, 13]


def test_invalid_tax_config_fails_before_open_receipt(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config({"tax_type": "vat20"}, path=isolated_config)

    result = service.print_check(sample_check, flask_logger)

    assert result["code"] == 400
    assert result["step"] == "validation"
    assert "tax_type" in result["message"]
    assert "openReceipt" not in service.fptr.calls
    assert "cancelReceipt" not in service.fptr.calls
