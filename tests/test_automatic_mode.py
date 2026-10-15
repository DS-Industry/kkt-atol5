"""Automatic-device settings and per-receipt machine number (FFD tag 1036)."""

from __future__ import annotations

from html import unescape
import json

import pytest

import conf
from cashierService import FFD_TAG_MACHINE_NUMBER


@pytest.fixture
def isolated_config(tmp_path):
    """Keep automatic-mode tests away from deployment instance/config.json."""
    cfg_path = tmp_path / "config.json"
    original_path = conf.CONFIG_PATH
    conf.CONFIG_PATH = cfg_path
    conf.load_config(cfg_path)
    try:
        yield cfg_path
    finally:
        conf.CONFIG_PATH = original_path
        conf.load_config()


def test_automatic_settings_defaults_and_roundtrip(isolated_config):
    assert conf.get_config()["automatic_mode"] is False
    assert conf.get_config()["machine_number"] == ""
    assert conf.get_config()["machine_numbers_by_bay"] == {}

    saved = conf.save_config(
        {
            "automatic_mode": True,
            "machine_numbers_by_bay": {
                "1": "WASH-0001",
                "02": "WASH-0002",
            },
        },
        path=isolated_config,
    )
    assert saved["automatic_mode"] is True
    assert saved["machine_numbers_by_bay"]["02"] == "WASH-0002"

    conf._config.clear()
    loaded = conf.load_config(isolated_config)
    assert loaded["automatic_mode"] is True
    assert loaded["machine_numbers_by_bay"] == {
        "1": "WASH-0001",
        "02": "WASH-0002",
    }
    assert conf.AUTOMATIC_MODE is True
    assert conf.MACHINE_NUMBERS_BY_BAY == loaded["machine_numbers_by_bay"]


@pytest.mark.parametrize(
    ("payload", "error_part"),
    [
        ({"automatic_mode": "maybe"}, "automatic_mode"),
        (
            {"automatic_mode": True, "machine_numbers_by_bay": {}},
            "required in automatic mode",
        ),
        ({"machine_numbers_by_bay": "1 WASH-0001"}, "bay=number"),
        ({"machine_numbers_by_bay": {"": "WASH-0001"}}, "post ID"),
        ({"machine_numbers_by_bay": {"1": ""}}, "must not be empty"),
        ({"machine_numbers_by_bay": {"1": "X" * 21}}, "at most 20"),
        ({"machine_numbers_by_bay": {"1": "WASH\t0001"}}, "control"),
        ({"machine_numbers_by_bay": "1=A\n1=B"}, "duplicate post ID"),
        (
            {"machine_numbers_by_bay": {"1": "WASH-1", "2": "WASH-1"}},
            "already assigned",
        ),
    ],
)
def test_automatic_settings_validation(isolated_config, payload, error_part):
    errors = conf.validate_settings_payload(payload)
    assert any(error_part in error for error in errors)


def test_admin_form_persists_mapping_and_status(isolated_config, app_db):
    client = app_db.app.test_client()
    response = client.post(
        "/admin/settings",
        data={
            "action": "save",
            "automatic_mode": "1",
            "machine_numbers_by_bay": "1=WASH-0001\n2=WASH-0002",
        },
    )

    assert response.status_code == 200
    cfg = conf.get_config()
    assert cfg["automatic_mode"] is True
    assert cfg["machine_numbers_by_bay"] == {
        "1": "WASH-0001",
        "2": "WASH-0002",
    }

    settings_page = unescape(client.get("/admin/settings").get_data(as_text=True))
    assert 'name="automatic_mode"' in settings_page
    assert "1=WASH-0001" in settings_page
    assert "2=WASH-0002" in settings_page

    status_page = unescape(client.get("/admin/status").get_data(as_text=True))
    assert "Автоматические устройства" in status_page
    assert "настроено постов: 2" in status_page
    assert "WASH-0001" in status_page


def test_admin_invalid_mapping_preserves_form_input(isolated_config, app_db):
    client = app_db.app.test_client()
    raw_mapping = "1=" + "X" * 21
    response = client.post(
        "/admin/settings",
        data={
            "action": "save",
            "automatic_mode": "1",
            "machine_numbers_by_bay": raw_mapping,
        },
    )

    assert response.status_code == 400
    page = unescape(response.get_data(as_text=True))
    assert raw_mapping in page
    assert '<option value="1" selected>Да</option>' in page


def test_automatic_receipt_uses_matching_machine_number(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {
            "automatic_mode": True,
            "machine_numbers_by_bay": {"1": "WASH-0001", "2": "WASH-0002"},
        },
        path=isolated_config,
    )
    check = {**sample_check, "bay": "2"}

    result = service.print_check(check, flask_logger)

    assert result == {"code": 201}
    open_params = service.fptr.open_receipt_params[-1]
    assert open_params[FFD_TAG_MACHINE_NUMBER] == "WASH-0002"
    assert 1001 not in open_params
    assert not any(call[0] == 1001 for call in service.fptr.set_param_calls)


def test_global_machine_number_applies_to_every_bay_and_without_bay(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {
            "automatic_mode": True,
            "machine_number": "00107602314817",
            "machine_numbers_by_bay": {"1": "LEGACY-ONE"},
        },
        path=isolated_config,
    )

    first = service.print_check({**sample_check, "bay": "7"}, flask_logger)
    second = service.print_check(sample_check, flask_logger)

    assert first == {"code": 201}
    assert second == {"code": 201}
    assert service.fptr.open_receipt_params[-2][FFD_TAG_MACHINE_NUMBER] == (
        "00107602314817"
    )
    assert service.fptr.open_receipt_params[-1][FFD_TAG_MACHINE_NUMBER] == (
        "00107602314817"
    )


def test_global_machine_number_satisfies_automatic_mode_validation(isolated_config):
    errors = conf.validate_settings_payload(
        {
            "automatic_mode": True,
            "machine_number": "00107602314817",
            "machine_numbers_by_bay": {},
        }
    )

    assert errors == []


def test_machine_number_is_set_after_operator_login(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {
            "cashier_name": "Иванов И.И., кассир",
            "automatic_mode": True,
            "machine_numbers_by_bay": {"1": "WASH-0001"},
        },
        path=isolated_config,
    )

    result = service.print_check({**sample_check, "bay": "1"}, flask_logger)

    assert result == {"code": 201}
    assert FFD_TAG_MACHINE_NUMBER not in service.fptr.operator_login_params[-1]
    assert service.fptr.open_receipt_params[-1][FFD_TAG_MACHINE_NUMBER] == "WASH-0001"
    assert service.fptr.calls.index("operatorLogin") < service.fptr.calls.index(
        "openReceipt"
    )


def test_disabled_mode_sends_no_machine_number(
    isolated_config, service, flask_logger, sample_check
):
    conf.save_config(
        {
            "automatic_mode": False,
            "machine_numbers_by_bay": {"1": "WASH-0001"},
        },
        path=isolated_config,
    )

    result = service.print_check(sample_check, flask_logger)

    assert result == {"code": 201}
    assert FFD_TAG_MACHINE_NUMBER not in service.fptr.open_receipt_params[-1]


@pytest.mark.parametrize("bay", [None, "9"])
def test_missing_or_unknown_bay_fails_before_receipt_open(
    isolated_config, service, flask_logger, sample_check, bay
):
    conf.save_config(
        {
            "automatic_mode": True,
            "machine_numbers_by_bay": {"1": "WASH-0001"},
        },
        path=isolated_config,
    )
    check = dict(sample_check)
    if bay is not None:
        check["bay"] = bay

    result = service.print_check(check, flask_logger)

    assert result["code"] == 400
    assert result["layer"] == "APP"
    assert result["step"] == "validation"
    assert "openReceipt" not in service.fptr.calls
    assert "registration" not in service.fptr.calls


def test_create_check_rejects_unmapped_bay_before_enqueue(
    isolated_config, app_db
):
    conf.save_config(
        {
            "automatic_mode": True,
            "machine_numbers_by_bay": {"1": "WASH-0001"},
        },
        path=isolated_config,
    )
    client = app_db.app.test_client()
    response = client.post(
        "/create-check",
        headers={
            "Data": json.dumps(
                {"name": "2", "bay": "9", "sum": 100, "type": "1"}
            )
        },
    )

    assert response.status_code == 400
    assert response.get_json()["step"] == "validation"
    with app_db.app.app_context():
        assert app_db.Check.query.count() == 0
