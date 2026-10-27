"""POS endpoints: create a check, list checks, and health."""
import json
import math

from flask import jsonify, request
from sqlalchemy import text

from app.data.config import get_config, resolve_machine_number
from app.data.models import Check
from app.runtime import app, db
from app.services.cashier import cashier_service
from app.services.faults import get_last_failure, next_action_for_layer
from app.services.qr_images import qr_image_url
from app.services.queue import (
    CHECK_HISTORY_LIMIT,
    STATUS_DONE,
    STATUS_PENDING,
    _check_to_dict,
    _flush_and_protect_new_check,
    _prune_checks_safely,
    _queue_counts_today,
    find_actual_check,
)


@app.route('/get-checks', methods=['GET'])
def get_checks():
    layer_filter = request.args.get("layer")
    query = Check.query
    if layer_filter:
        query = query.filter_by(layer=layer_filter)
    checks = query.order_by(Check.id.desc()).limit(CHECK_HISTORY_LIMIT).all()
    return jsonify([_check_to_dict(c) for c in checks]), 200


@app.route('/create-check', methods=['POST'])
def create_check():
    try:
        data_str = request.headers.get('Data')

        if not data_str:
            app.logger.warning("No data provided in headers")
            return jsonify({"error": "No data provided in headers", "code": 400}), 400

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            app.logger.error(f"Invalid JSON format: {data_str}")
            return jsonify({"error": "Invalid JSON format", "code": 400}), 400

        if not isinstance(data, dict):
            app.logger.warning("Check payload must be a JSON object")
            return jsonify({"error": "Invalid JSON payload", "code": 400}), 400

        nameType = data.get('name')
        bay = data.get('bay')
        raw_sum = data.get('sum')
        type_value = data.get('type')
        name = ''

        try:
            # bool is a JSON logical value, even though Python float() accepts it.
            if isinstance(raw_sum, bool):
                raise ValueError
            sum_value = float(raw_sum)
        except (TypeError, ValueError):
            app.logger.warning(f"Missing or invalid sum: {data}")
            return jsonify({"error": "Invalid sum", "code": 400}), 400
        if not math.isfinite(sum_value):
            app.logger.warning(f"Non-finite sum: {data}")
            return jsonify({"error": "Invalid sum", "code": 400}), 400

        # Validate before building the display name: concatenating None/int used
        # to raise TypeError and turn malformed client input into HTTP 500.
        if not isinstance(bay, str) or not bay.strip():
            app.logger.warning(f"Missing or invalid bay: {data}")
            return jsonify({"error": "Missing required fields", "code": 400}), 400

        _, automatic_errors = resolve_machine_number(get_config(), bay)
        if automatic_errors:
            message = "; ".join(automatic_errors)
            app.logger.warning("Automatic-device validation failed: %s", message)
            return jsonify({
                "error": message,
                "message": message,
                "code": 400,
                "layer": "APP",
                "step": "validation",
            }), 400

        if nameType == '1':
            name = 'Робот ' + bay
        elif nameType == '2':
            name = 'Пост ' + bay
        else:
            name = 'Пылесос ' + bay

        if not all([name, bay, sum_value is not None, type_value is not None]):
            app.logger.warning(f"Missing required fields: {data}")
            return jsonify({"error": "Missing required fields", "code": 400}), 400

        app.logger.info(
            f"Creating check: Name={name}, Bay={bay}, Sum={sum_value}, Type={type_value}"
        )
        new_check = Check(
            name=name,
            bay=bay,
            sum=sum_value,
            type=type_value,
            status=STATUS_PENDING,
            isProcessed=False,
            isQr=False,
        )

        db.session.add(new_check)
        # Flush allocates the id while the row is still invisible to the
        # scheduler's separate transaction. Register protection before commit,
        # then retain it across the complete QR wait.
        with _flush_and_protect_new_check(new_check) as check_id:
            db.session.commit()
            _prune_checks_safely("check creation")

            # F-Q-04: poll/wait keyed by check id (not commodity name)
            wait_result = find_actual_check(new_check.name, check_id=check_id)
        http_code = wait_result.get("code", 500)

        if http_code == 201:
            app.logger.info(
                f"QR code generated: {wait_result.get('qr')} for check {check_id}"
            )
            return jsonify({
                "message": "Check created successfully",
                "qr": wait_result["qr"],
                "qrImageUrl": qr_image_url(check_id, wait_result["qr"]),
                "qrGenerated": wait_result["qrGenerated"],
                "dateTime": wait_result["dateTime"],
                "id": check_id,
                "status": wait_result.get("status", STATUS_DONE),
                "code": 201,
            }), 201

        # HTTP status matches outcome (F-API-04 / AGENTS.md §5); 504 includes id+status (F-Q-05)
        body = {
            "message": wait_result.get("message", "Check processing failed"),
            "id": wait_result.get("id", check_id),
            "status": wait_result.get("status"),
            "code": http_code,
        }
        if wait_result.get("error_code") is not None:
            body["error_code"] = wait_result["error_code"]
        if wait_result.get("error_description") is not None:
            body["error_description"] = wait_result["error_description"]
        if wait_result.get("layer") is not None:
            body["layer"] = wait_result["layer"]
            body["where"] = wait_result.get("where") or wait_result["layer"]
            body["what_to_do_next"] = wait_result.get("what_to_do_next") or next_action_for_layer(
                wait_result["layer"]
            )
        if wait_result.get("step") is not None:
            body["step"] = wait_result["step"]
        if wait_result.get("retryable"):
            body["retryable"] = True
        app.logger.error(f"create-check failed: {body}")
        return jsonify(body), http_code

    except Exception as e:
        app.logger.error("Error processing check: %s", e, exc_info=True)
        return jsonify({
            "error": "Failed to create or wait for check",
            "code": 500,
            "layer": "APP",
            "where": "APP",
            "what_to_do_next": next_action_for_layer("APP"),
        }), 500


@app.route("/health", methods=["GET"])
def health():
    """
    F-OPS-02 / F-DIAG-05: DB ok + device open + shift (best-effort).
    HTTP 200 vs 503; JSON code matches HTTP status.
    Shift query must not reconnect (avoid F-CONN-04 backoff under RLock).
    """
    checks = {
        "db": {"pass": False},
        "device_open": {"pass": False},
        "shift": {"pass": False, "best_effort": True},
    }
    overall_ok = True
    layer = None

    try:
        db.session.execute(text("SELECT 1"))
        checks["db"] = {"pass": True, "layer": "APP"}
    except Exception as e:
        app.logger.error("Health DB check failed: %s", e, exc_info=True)
        checks["db"] = {
            "pass": False,
            "layer": "APP",
            "message": "Database check failed",
        }
        overall_ok = False
        layer = "APP"

    opened = cashier_service.is_device_opened()
    if opened.get("opened"):
        checks["device_open"] = {"pass": True, "layer": "LINK", "opened": True}
    else:
        checks["device_open"] = {
            "pass": False,
            "layer": "LINK",
            "opened": False,
            "error_code": opened.get("error_code"),
            "message": opened.get("message") or "Device not opened",
        }
        overall_ok = False
        layer = layer or "LINK"

    # Best-effort shift only when already open — never reconnect on /health
    if opened.get("opened"):
        shift = cashier_service.get_shift_status(reconnect=False)
        if shift.get("code") in (200, 400, 450):
            checks["shift"] = {
                "pass": True,
                "best_effort": True,
                "layer": "KKT",
                "shift_code": shift.get("code"),
                "shift": shift.get("shift"),
            }
        else:
            checks["shift"] = {
                "pass": False,
                "best_effort": True,
                "layer": shift.get("layer", "KKT"),
                "message": shift.get("message"),
                "error_code": shift.get("error_code"),
            }
            overall_ok = False
            layer = layer or shift.get("layer", "KKT")
    else:
        checks["shift"] = {
            "pass": False,
            "best_effort": True,
            "skipped": True,
            "layer": "LINK",
            "message": "Skipped while device not open",
        }

    http_code = 200 if overall_ok else 503
    body = {
        "code": http_code,
        "ok": overall_ok,
        "status": "healthy" if overall_ok else "unhealthy",
        "checks": checks,
        "queue": _queue_counts_today(),
        "connection": cashier_service.connection_info(),
        "layer": layer,
        "where": layer,
        "what_to_do_next": next_action_for_layer(layer) if layer else None,
        "last_failure": get_last_failure(),
    }
    return jsonify(body), http_code
