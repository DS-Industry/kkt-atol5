from io import BytesIO
from urllib.parse import urlsplit

import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from PIL import Image

from app.services.qr_images import _card_details, _font, _wrap, qr_image_url, register_qr_images

QR = "t=20260914T2009&s=750.00&fn=7380440902802880&i=4261&fp=830583019&n=1"


@pytest.fixture
def qr_app(tmp_path):
    app = Flask(__name__, instance_path=str(tmp_path))
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://")
    db = SQLAlchemy(app)

    class Receipt(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        qr = db.Column(db.String)
        status = db.Column(db.String)
        isQr = db.Column(db.Boolean)
        name = db.Column(db.String, default="Робот 1")
        bay = db.Column(db.String, default="1")
        type = db.Column(db.String, default="1")
        sum = db.Column(db.Float, default=750)

    register_qr_images(app, db, Receipt)
    with app.app_context():
        db.create_all()
        db.session.add(Receipt(id=1, qr=QR, status="done", isQr=True))
        db.session.commit()
        with app.test_request_context(base_url="http://192.168.28.251:5000"):
            url = qr_image_url(1, QR)
        yield app, db, Receipt, url


def test_png_exact_payload(qr_app, monkeypatch):
    app, db, model, url = qr_app
    import qrcode
    original = qrcode.QRCode.add_data
    seen = []

    def capture(self, data, *args, **kwargs):
        seen.append(data)
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(qrcode.QRCode, "add_data", capture)
    assert url.startswith("http://192.168.28.251:5000/qr/1/")
    response = app.test_client().get(urlsplit(url).path)
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    image = Image.open(BytesIO(response.data))
    assert image.format == "PNG"
    assert image.size[0] == 600
    assert image.size[1] > image.size[0]
    assert seen == [QR]


def test_plain_qr_and_card_have_identical_qr_pixels(qr_app):
    app, _, _, url = qr_app
    client = app.test_client()
    path = urlsplit(url).path
    plain = Image.open(BytesIO(client.get(path + "?plain=1").data)).convert("RGB")
    card = Image.open(BytesIO(client.get(path).data)).convert("RGB")
    assert plain.width == plain.height
    left = (card.width - plain.width) // 2
    top = card.height - 68 - plain.height
    assert card.crop((left, top, left + plain.width, top + plain.height)).tobytes() == plain.tobytes()


def test_card_labels_from_receipt(qr_app):
    _, db, model, _ = qr_app
    row = db.session.get(model, 1)
    labels = "\n".join(item[0] for item in _card_details(row))
    for expected in ["Робот 1", "750,00 руб.", "Пост / устройство: 1",
                     "Безналичные", "14.09.2026 20:09"]:
        assert expected in labels
    assert "Функция" not in labels
    row.type = "0"
    assert "Способ оплаты: Наличные" in [item[0] for item in _card_details(row)]


def test_long_cyrillic_wrap():
    font = _font(24)
    text = "Очень длинное название поста " + "Ф" * 100
    lines = _wrap(text, font, 536)
    assert len(lines) > 1
    assert all(font.getlength(line) <= 536 for line in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")


@pytest.mark.parametrize("token", ["0" * 64, "bad", "я" * 64])
def test_invalid_token(qr_app, token):
    app, _, _, _ = qr_app
    assert app.test_client().get(f"/qr/1/{token}.png").status_code == 404


@pytest.mark.parametrize("change", ["deleted", "pending", "no_qr", "reused_id"])
def test_unavailable_receipt(qr_app, change):
    app, db, model, url = qr_app
    row = db.session.get(model, 1)
    if change == "deleted":
        db.session.delete(row)
    elif change == "pending":
        row.status = "pending"
    elif change == "no_qr":
        row.isQr = False
    else:
        row.qr = "replacement"
    db.session.commit()
    assert app.test_client().get(urlsplit(url).path).status_code == 404


def test_key_persists(qr_app):
    app, db, model, url = qr_app
    restarted = Flask("restart", instance_path=app.instance_path)
    register_qr_images(restarted, db, model)
    with restarted.test_request_context(base_url="http://192.168.28.251:5000"):
        assert qr_image_url(1, QR) == url


def test_history_additive_url(app_db):
    main = app_db
    row = main.Check(name="Робот 1", bay="1", sum=750, type="1",
                     status="done", isProcessed=True, isQr=True, qr=QR)
    main.db.session.add(row)
    main.db.session.commit()
    with main.app.test_request_context():
        data = main._check_to_dict(row)
    assert data["qr"] == QR
    assert "/qr/" in data["qrImageUrl"]
    response = main.app.test_client().get(urlsplit(data["qrImageUrl"]).path)
    assert response.status_code == 200


def test_create_response_url(app_db, monkeypatch):
    import json
    main = app_db

    def finished(name, check_id):
        row = main.db.session.get(main.Check, check_id)
        row.status = "done"
        row.isQr = True
        row.isProcessed = True
        row.qr = QR
        main.db.session.commit()
        return dict(code=201, qr=QR, qrGenerated=True, dateTime="2026-09-14T20:09:00")

    import app.http.api as http_api

    monkeypatch.setattr(http_api, "find_actual_check", finished)
    monkeypatch.setattr(http_api, "resolve_machine_number", lambda *args: ("test", []))
    client = main.app.test_client()
    response = client.post("/create-check", headers={"Data": json.dumps(
        dict(name="1", bay="1", sum=750, type="1"))})
    assert response.status_code == 201
    data = response.get_json()
    assert data["qr"] == QR and data["qrGenerated"] is True
    assert client.get(urlsplit(data["qrImageUrl"]).path).mimetype == "image/png"
