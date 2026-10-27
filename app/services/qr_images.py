"""Signed, on-demand PNG images of the exact fiscal QR stored in a receipt."""
import hashlib
import hmac
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import secrets
from urllib.parse import parse_qs

import qrcode
from flask import abort, current_app, make_response, request, send_file, url_for
from PIL import Image, ImageDraw, ImageFont
from app.services.receipt_render import ofd_receipt_url


_LATEST_QR_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QR чека</title>
<style>
html,body{margin:0;min-height:100%;background:white}
body{font-family:Arial,sans-serif;text-align:center}
#receipt{display:block;width:100%;max-width:680px;height:auto;margin:0 auto}
#message{padding:24px;text-align:center;font-size:24px;color:#444}
[hidden]{display:none!important}
</style></head><body>
<div id="message" role="status">Ожидание чека…</div>
<img id="receipt" alt="QR-код чека" hidden>
<script>
(function () {
  var img = document.getElementById('receipt');
  var message = document.getElementById('message');
  var currentUrl = null;
  function clear(text) {
    img.hidden = true;
    img.removeAttribute('src');
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = null;
    message.textContent = text;
    message.hidden = false;
  }
  function refresh() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/qr/latest.png', true);
    xhr.responseType = 'blob';
    xhr.timeout = 8000;
    xhr.onload = function () {
      if (xhr.status === 204) {
        clear('Ожидание чека…');
      } else if (xhr.status === 200 && xhr.response.type === 'image/png') {
        var nextUrl = URL.createObjectURL(xhr.response);
        img.onload = function () {
          if (currentUrl) URL.revokeObjectURL(currentUrl);
          currentUrl = nextUrl;
          img.hidden = false;
          message.hidden = true;
        };
        img.onerror = function () {
          URL.revokeObjectURL(nextUrl);
          clear('Не удалось показать чек');
        };
        img.src = nextUrl;
      } else {
        clear('Не удалось получить чек');
      }
    };
    xhr.onerror = xhr.ontimeout = function () { clear('Нет связи с сервером чеков'); };
    xhr.onloadend = function () { window.setTimeout(refresh, 2000); };
    xhr.send();
  }
  refresh();
}());
</script></body></html>"""


@lru_cache(maxsize=8)
def _font(size, bold=False):
    # Both production Linux and local Windows fonts support Cyrillic.
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu") / filename,
        Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("A Cyrillic font is required for receipt images (DejaVu Sans)")


def _wrap(text, font, max_width):
    """Pixel-based wrapping, including long unbroken device names."""
    lines = []
    line = ""
    for char in " ".join(str(text).split()):
        if font.getlength(line + char) > max_width and line:
            # Break at the most recent space when possible.
            head, sep, tail = line.rpartition(" ")
            if sep and head:
                lines.append(head)
                line = tail + char
            else:
                lines.append(line)
                line = char
        else:
            line += char
    if line.strip():
        lines.append(line.strip())
    return lines


def _card_details(check):
    fiscal = parse_qs(check.qr, keep_blank_values=True)
    # Use the fiscal amount/time, not the Orange Pi clock, which may differ.
    raw_amount = fiscal.get("s", [getattr(check, "sum", None)])[0]
    try:
        amount = Decimal(str(raw_amount))
        if not amount.is_finite():
            raise InvalidOperation
        amount_label = f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " руб."
    except (InvalidOperation, ValueError):
        amount_label = "Сумма не указана"
    date_label = "не указана"
    for pattern in ("%Y%m%dT%H%M", "%Y%m%dT%H%M%S"):
        try:
            date_label = datetime.strptime(fiscal.get("t", [""])[0], pattern).strftime("%d.%m.%Y %H:%M")
            break
        except ValueError:
            pass
    payment = getattr(check, "type", None)
    # Keep identical mapping to CashierService: 0=cash, all other supplied types=electronic.
    payment_label = "не указан" if payment is None else (
        "Наличные" if str(payment) == "0" else "Безналичные")
    return [
        ("Полный документ не сохранён; доступен QR чека", 20, False),
        ("Информация об оплате", 28, True),
        (getattr(check, "name", None) or "Услуга", 34, True),
        (amount_label, 42, True),
        ("Пост / устройство: " + str(getattr(check, "bay", None) or "не указан"), 24, False),
        ("Способ оплаты: " + payment_label, 24, False),
        ("Дата чека: " + date_label, 24, False),
    ]


def _payment_card(check, qr_image):
    # qrcode's wrapper .width is a module count, not a pixel dimension.
    qr_image = qr_image.convert("RGB")
    width = max(600, qr_image.width + 64)
    margin = 32
    prepared = []
    y = margin
    for text, size, bold in _card_details(check):
        font = _font(size, bold)
        for line in _wrap(text, font, width - 2 * margin):
            prepared.append((line, font, y))
            y += size + 10
        y += 10
    qr_top = y + 20
    footer_top = qr_top + qr_image.height + 14
    canvas = Image.new("RGB", (width, footer_top + 54), "white")
    draw = ImageDraw.Draw(canvas)
    for text, font, top in prepared:
        draw.text((margin, top), text, font=font, fill="black")
    draw.line((margin, y, width - margin, y), fill="black", width=1)
    # Paste at native resolution; retain all four quiet-zone modules.
    canvas.paste(qr_image, ((width - qr_image.width) // 2, qr_top))
    footer_font = _font(22)
    text = "Сканируйте QR для проверки чека"
    x = (width - footer_font.getlength(text)) / 2
    draw.text((x, footer_top), text, font=footer_font, fill="black")
    return canvas


def register_qr_images(app, db, check_model):
    key_path = Path(app.instance_path) / "qr-image.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with key_path.open("xb") as stream:
            key_path.chmod(0o600)
            stream.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    key = key_path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("Invalid QR image signing key")
    app.config["QR_IMAGE_SIGNING_KEY"] = key

    @app.get("/qr", strict_slashes=False)
    def latest_qr_page():
        response = make_response(_LATEST_QR_PAGE)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/qr/latest.png")
    def latest_qr_image():
        # Completion time matters when an older queued receipt finishes later.
        check = db.session.execute(
            db.select(check_model).where(
                check_model.status == "done", check_model.isQr.is_(True),
                check_model.qr.isnot(None), check_model.qr != "",
            ).order_by(check_model.dateProcessed.desc(), check_model.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if check is None:
            response = make_response("", 204)
            response.headers["Cache-Control"] = "no-store"
            return response
        return fiscal_qr_image(check.id, _signature(check.id, check.qr))

    @app.get("/qr/<int:check_id>/<token>.png")
    def fiscal_qr_image(check_id, token):
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            abort(404)
        check = db.session.get(check_model, check_id)
        if (check is None or check.status != "done" or not check.isQr
                or not check.qr or not hmac.compare_digest(
                    _signature(check_id, check.qr), token)):
            abort(404)
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=8, border=4)
        # The visible QR opens the full receipt at First OFD. The original
        # fiscal QR string stays persisted and is still available via
        # ?plain=1 for FNS/OFD verification workflows.
        qr_payload = check.qr if request.args.get("plain") == "1" else ofd_receipt_url(check.qr)
        qr.add_data(qr_payload)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        # The public image contains only the QR itself.  Its default payload is
        # the First OFD receipt URL; ?plain=1 keeps the original fiscal payload.
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        response = send_file(buffer, mimetype="image/png",
                             download_name=f"check-{check_id}-qr.png")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def _signature(check_id, qr):
    return hmac.new(current_app.config["QR_IMAGE_SIGNING_KEY"],
                    f"{check_id}\n{qr}".encode("utf-8"), hashlib.sha256).hexdigest()


def qr_image_url(check_id, qr):
    return url_for("fiscal_qr_image", check_id=check_id,
                   token=_signature(check_id, qr), _external=True)
