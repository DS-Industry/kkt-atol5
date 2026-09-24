"""Synthetic FN documents only; run in an isolated project copy (main has boot I/O)."""
import copy
import json
import sqlite3
from io import BytesIO
from urllib.parse import urlsplit

import pytest
import qrcode
from PIL import Image

from qr_images import _font, _wrap, qr_image_url
from receipt_render import receipt_image, receipt_lines


QR = "t=20260102T0304&s=500.00&fn=9999999999999999&i=42&fp=12345&n=1"


@pytest.fixture
def fiscal_document():
    return {
        "documentTLV": {
            "qr": QR, "short": False, "fiscalDocumentType": "receipt",
            "1048": "ТЕСТОВАЯ ОРГАНИЗАЦИЯ", "1018": "000000000000",
            "1009": "Тестовый адрес", "1187": "Тестовый пост",
            "1012": "2026-01-02T03:04:00", "1054": 1, "1055": 32,
            "1042": 2, "1038": 7, "1020": 500.0,
            "1031": 200.0, "1081": 300.0, "1105": 500.0,
            "1041": "9999999999999999", "1040": 42,
            "1037": "0000000000000001", "1013": "TEST-KKT-1",
            "1036": "TEST-POST-2", "1209": 2, "1077": "000000003039",
            "1059": [{"1030": "Тестовая мойка", "1023": 2, "1079": 250.0,
                      "1043": 500.0, "1199": 6, "1212": 4, "1214": 4}],
        },
        "receiptContext": {"1048": "НЕ ИСПОЛЬЗОВАТЬ ВМЕСТО TLV"},
        "syntheticMetadata": {"testOnly": True},
    }


def rendered_text(document, qr=QR):
    return "\n".join(row[0] for row in receipt_lines(document, qr))


def test_receipt_contains_items_payments_and_fiscal_identifiers(fiscal_document):
    result = rendered_text(fiscal_document)
    for expected in (
        "ТЕСТОВАЯ ОРГАНИЗАЦИЯ", "КАССОВЫЙ ЧЕК", "ПРИХОД",
        "02.01.2026 03:04:00", "Тестовая мойка", "Количество: 2",
        "Цена: 250,00", "Стоимость: 500,00", "ИТОГО: 500,00",
        "Наличными: 200,00", "Безналичными: 300,00", "Сумма без НДС: 500,00",
        "ФН: 9999999999999999", "ФД: 42", "ФПД: 12345",
        "РН ККТ: 0000000000000001", "ЗН ККТ: TEST-KKT-1",
        "№ автомата: TEST-POST-2", "Версия ФФД: 1.05", "СНО: Патент",
        "Предмет расчёта: Услуга", "Способ расчёта: Полный расчёт",
    ):
        assert expected in result
    assert "НЕ ИСПОЛЬЗОВАТЬ" not in result
    assert "QR code generated" not in result


def test_cashier_not_invented_from_context(fiscal_document):
    fiscal_document["receiptContext"].update({
        "1021": "КОНТЕКСТНЫЙ КАССИР", "1203": "000000000099",
        "1020": 999999, "1031": 999999,
    })
    result = rendered_text(fiscal_document)
    assert "Кассир" not in result
    assert "кассира" not in result
    assert "КОНТЕКСТНЫЙ" not in result
    assert "999999" not in result.replace("9999999999999999", "")


def test_cashier_present_in_fiscal_document_is_not_hidden(fiscal_document):
    fiscal_document["documentTLV"].update({"1021": "ТЕСТ КАССИР", "1203": "000000000099"})
    result = rendered_text(fiscal_document)
    assert "Кассир: ТЕСТ КАССИР" in result
    assert "ИНН кассира: 000000000099" in result


@pytest.mark.parametrize("conflict_tag", ["1018", "1037"])
def test_conflicting_context_cannot_fill_missing_identity(fiscal_document, conflict_tag):
    del fiscal_document["documentTLV"]["1048"]
    fiscal_document["receiptContext"].update({
        conflict_tag: "WRONG-IDENTITY", "1048": "WRONG-CONTEXT-NAME",
        "1117": "wrong@example.invalid",
    })
    result = rendered_text(fiscal_document)
    assert "WRONG" not in result
    assert "wrong@example.invalid" not in result


def test_matching_context_can_fill_cliche_but_not_override_tlv(fiscal_document):
    del fiscal_document["documentTLV"]["1048"]
    fiscal_document["receiptContext"].update({
        "1048": "Тестовое клише", "1018": "000000000000",
        "1009": "НЕВЕРНЫЙ АДРЕС", "1117": "test@example.invalid",
    })
    result = rendered_text(fiscal_document)
    assert "Организация: Тестовое клише" in result
    assert "test@example.invalid" in result
    assert "Тестовый адрес" in result
    assert "НЕВЕРНЫЙ АДРЕС" not in result


@pytest.mark.parametrize("bad_tlv", [{}, {"qr": QR.replace("i=42", "i=43")}, []])
def test_missing_or_different_document_qr_is_rejected(bad_tlv):
    with pytest.raises(ValueError, match="does not match"):
        receipt_lines({"documentTLV": bad_tlv}, QR)


def test_nested_unknown_tags_are_retained_and_source_not_mutated(fiscal_document):
    fiscal_document["documentTLV"]["9990"] = {"9991": [{"9992": "nested-value"}, "list-value"]}
    fiscal_document["documentTLV"]["1059"][0]["9993"] = {"9994": "item-extra"}
    original = copy.deepcopy(fiscal_document)
    result = rendered_text(fiscal_document)
    for expected in ("Тег 9990", "Тег 9991", "Тег 9992: nested-value",
                     "list-value", "Тег 9993", "Тег 9994: item-extra"):
        assert expected in result
    assert fiscal_document == original
    assert receipt_lines(json.dumps(fiscal_document), QR) == receipt_lines(fiscal_document, QR)


def test_short_document_is_explicitly_labelled(fiscal_document):
    fiscal_document["documentTLV"]["short"] = True
    assert "сокращённый документ" in rendered_text(fiscal_document)


def test_receipt_image_preserves_exact_qr_pixels(fiscal_document):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    code.add_data(QR)
    code.make(fit=True)
    qr_image = code.make_image(fill_color="black", back_color="white").convert("RGB")
    result = receipt_image(fiscal_document, QR, qr_image, _font, _wrap)
    assert result.width >= 680
    assert result.height > qr_image.height
    left = (result.width - qr_image.width) // 2
    top = result.height - 70 - qr_image.height
    assert result.crop((left, top, left + qr_image.width, top + qr_image.height)).tobytes() == qr_image.tobytes()


def test_successful_job_persists_entire_fn_response(app_db, monkeypatch, fiscal_document):
    main = app_db
    row = main.Check(name="Тестовая мойка", bay="2", type="1", sum=500, status="pending")
    main.db.session.add(row)
    main.db.session.commit()
    check_id = row.id
    monkeypatch.setattr(main, "_ensure_shift_ready", lambda app: {"code": 200})
    monkeypatch.setattr(main.cashier_service, "print_check", lambda *args: {"code": 201})
    monkeypatch.setattr(main.cashier_service, "readLastReciept", lambda: json.dumps(fiscal_document))
    main.job1()
    main.db.session.expire_all()
    stored = main.db.session.get(main.Check, check_id)
    assert stored.status == "done" and stored.isProcessed and stored.isQr
    assert stored.qr == QR
    assert json.loads(stored.fiscal_document) == fiscal_document


def test_signed_and_latest_routes_render_saved_document(app_db, fiscal_document):
    main = app_db
    row = main.Check(name="НЕ КЛИШЕ", bay="2", type="1", sum=999,
                     status="done", isProcessed=True, isQr=True, qr=QR,
                     fiscal_document=json.dumps(fiscal_document))
    main.db.session.add(row)
    main.db.session.commit()
    with main.app.test_request_context():
        path = urlsplit(qr_image_url(row.id, QR)).path
    client = main.app.test_client()
    response = client.get(path)
    latest = client.get("/qr/latest.png")
    plain = client.get(path + "?plain=1")
    assert response.status_code == latest.status_code == plain.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    assert latest.data == response.data
    full_image = Image.open(BytesIO(response.data)).convert("RGB")
    qr_image = Image.open(BytesIO(plain.data)).convert("RGB")
    expected = receipt_image(fiscal_document, QR, qr_image, _font, _wrap)
    assert full_image.tobytes() == expected.tobytes()
    assert full_image.size == expected.size


def test_additive_schema_migration_preserves_legacy_qr_and_rows(app_db, tmp_path):
    from tests.conftest import _rebind_sqlite
    main = app_db
    legacy = tmp_path / "before-fiscal-document.db"
    with sqlite3.connect(legacy) as connection:
        connection.execute('''CREATE TABLE "check" (
            id INTEGER PRIMARY KEY, name VARCHAR(100), bay VARCHAR(50),
            price FLOAT, quantity INTEGER, type VARCHAR(50), sum FLOAT,
            isProcessed BOOLEAN, isQr BOOLEAN, dateCreated DATETIME,
            dateProcessed DATETIME, qr VARCHAR(255))''')
        connection.execute('''INSERT INTO "check"
            (id,name,bay,type,sum,isProcessed,isQr,qr) VALUES (1,?,?,?,?,?,?,?)''',
            ("Тестовый архив", "2", "1", 500.0, 1, 1, QR))
    _rebind_sqlite(main, legacy)
    main._ensure_schema()
    main._ensure_schema()
    row = main.db.session.get(main.Check, 1)
    assert row.name == "Тестовый архив" and row.qr == QR and row.sum == 500
    assert row.status == "done" and row.fiscal_document is None
    assert main.Check.query.count() == 1
