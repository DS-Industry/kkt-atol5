import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_WALL_CLOCK = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_QR_TIME = re.compile(r"(?:^|[?&])t=(\d{8}T\d{4}(?:\d{2})?)(?:&|$)")


def fiscal_endpoint(base_url):
    return str(base_url).strip().rstrip("/") + "/data/fiscal"


def whole_rubles(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def payment_type_label(check_type):
    if str(check_type) == "0":
        return "Наличные"
    return "Безналичные"


def _wall_clock(text):
    if _WALL_CLOCK.fullmatch(text):
        return text
    return None


def operation_time(fiscal_document, qr):
    tag = None
    if fiscal_document:
        try:
            data = (
                json.loads(fiscal_document)
                if isinstance(fiscal_document, str)
                else fiscal_document
            )
        except (TypeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            raw = data.get("documentTLV", {}).get("1012")
            if isinstance(raw, str):
                text = raw.strip()
                if _WALL_CLOCK.fullmatch(text):
                    tag = text
                elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text):
                    tag = _wall_clock(text + ":00")
    if tag:
        return tag
    match = _QR_TIME.search(qr or "")
    if not match:
        return None
    day, clock = match.group(1).split("T")
    if len(clock) == 4:
        clock = clock + "00"
    return _wall_clock(
        f"{day[0:4]}-{day[4:6]}-{day[6:8]}T{clock[0:2]}:{clock[2:4]}:{clock[4:6]}"
    )


def missing_state_fields(snapshot):
    missing = []
    if not isinstance(snapshot.get("treasurerLinkOpen"), bool):
        missing.append("treasurerLinkOpen")
    if snapshot.get("shiftStatus") not in ("OPEN", "CLOSED", "EXPIRED"):
        missing.append("shiftStatus")
    for name in (
        "fnMemoryOverflow",
        "fnResourceExhausted",
        "fnReplacementRequired",
    ):
        if not isinstance(snapshot.get(name), bool):
            missing.append(name)
    count = snapshot.get("ofdUnsentDocumentsCount")
    if type(count) is not int or count < 0:
        missing.append("ofdUnsentDocumentsCount")
    return missing


def _driver_error_code(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or not text.lstrip("-").isdigit():
        return None
    return int(text)


def state_payload(succeeded, snapshot, step=None, error_code=None, error_text=None):
    state = {
        "treasurerLinkOpen": snapshot["treasurerLinkOpen"],
        "shiftStatus": snapshot["shiftStatus"],
        "receiptAttemptSucceeded": bool(succeeded),
        "fnMemoryOverflow": snapshot["fnMemoryOverflow"],
        "fnResourceExhausted": snapshot["fnResourceExhausted"],
        "fnReplacementRequired": snapshot["fnReplacementRequired"],
        "ofdUnsentDocumentsCount": snapshot["ofdUnsentDocumentsCount"],
    }
    if step:
        state["driverErrorStep"] = str(step)[:50]
    code = _driver_error_code(error_code)
    if code is not None:
        state["driverErrorCode"] = code
    if error_text:
        state["driverErrorText"] = str(error_text)[:500]
    return state


def build_packet(check, snapshot, pos_id):
    missing = missing_state_fields(snapshot)
    if missing or not isinstance(pos_id, int) or isinstance(pos_id, bool) or pos_id <= 0:
        return None, missing or ["posId"]
    succeeded = check["status"] == "done"
    state = state_payload(
        succeeded,
        snapshot,
        step=check.get("step"),
        error_code=check.get("error_code"),
        error_text=check.get("error_text"),
    )
    if not succeeded:
        return {"posId": pos_id, "state": state}, []
    credit_missing = []
    operation = operation_time(check.get("fiscal_document"), check.get("qr"))
    amount = whole_rubles(check.get("sum"))
    device_name = str(check.get("name") or "").strip()
    qr = str(check.get("qr") or "").strip()
    if not operation:
        credit_missing.append("operationTime")
    if amount is None:
        credit_missing.append("amount")
    if not device_name:
        credit_missing.append("deviceName")
    if not qr:
        credit_missing.append("qr")
    if credit_missing:
        return None, credit_missing
    return {
        "posId": pos_id,
        "operationTime": operation,
        "amount": amount,
        "deviceName": device_name,
        "paymentType": payment_type_label(check.get("type")),
        "qr": qr,
        "state": state,
    }, []


def deliver(base_url, api_key, body, timeout=5):
    request = Request(
        fiscal_endpoint(base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("X-API-KEY", api_key)
    try:
        with urlopen(request, timeout=timeout) as response:
            return getattr(response, "status", None) == 200
    except HTTPError as exc:
        return exc.code == 200
    except (URLError, TimeoutError, OSError):
        return False
