"""Admin pages. Unauthenticated; trusted LAN only."""
from flask import jsonify, redirect, render_template, request, url_for

import app.services.qr_displays as qr_displays
from app.data.config import (
    LOG_PATH,
    TAX_TYPE_LABELS,
    coerce_settings_updates,
    get_config,
    normalize_automatic_mode,
    normalize_machine_number,
    normalize_machine_numbers_by_bay,
    normalize_send_cashier_to_kkt,
    reset_config,
    save_config,
    validate_settings_payload,
)
from app.data.models import Check, QRDisplayDelivery
from app.http.diagnostics import run_diagnostics_ladder
from app.runtime import app
from app.services.cashier import cashier_service
from app.services.faults import get_last_failure, next_action_for_layer
from app.services.queue import (
    CHECK_HISTORY_LIMIT,
    _check_to_dict,
    _qr_display_io_lock,
    _queue_counts_today,
)


def _tail_log_lines(path, max_lines, level_filter=None):
    """Return (text, error_message)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return "", f"Log file not found: {path}"
    except OSError as exc:
        return "", f"Cannot read log: {exc}"

    if level_filter:
        needle = level_filter.upper()
        lines = [ln for ln in lines if needle in ln.upper()]
    lines = lines[-max(1, int(max_lines)) :]
    return "".join(lines), None


def _settings_from_request():
    """Accept JSON body or form fields for Settings."""
    if request.is_json:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}
    form = request.form
    keys = (
        "connection_mode",
        "kkt_ip",
        "kkt_tcp_port",
        "library_path",
        "cashier_name",
        "cashier_inn",
        "send_cashier_to_kkt",
        "automatic_mode",
        "machine_number",
        "machine_numbers_by_bay",
        "tax_type",
        "http_host",
        "http_port",
        "qr_wait_timeout_sec",
        "shift_open_timeout_sec",
        "log_path",
        "max_log_lines",
        "monitoring_url",
        "monitoring_pos_id",
    )
    return {k: form.get(k) for k in keys if form.get(k) is not None}


def _settings_view(cfg):
    view = dict(cfg)
    view.pop("monitoring_api_key", None)
    return view


# ---------------------------------------------------------------------------
# Admin GUI (Screens A–D). Unauthenticated — trusted LAN MVP only (F-CFG / AC-6).
# Do not expose /admin* beyond the site network; Auth/PIN is out of scope for Phase C.
# ---------------------------------------------------------------------------


@app.route("/admin")
@app.route("/admin/status")
def admin_status():
    """Screen A — Status."""
    connection = cashier_service.connection_info()
    opened = cashier_service.is_device_opened()
    shift_label = "—"
    layer = None
    if opened.get("opened"):
        shift = cashier_service.get_shift_status(reconnect=False)
        code = shift.get("code")
        if code == 200:
            shift_label = "OPEN"
        elif code == 400:
            shift_label = "CLOSED"
        elif code == 450:
            shift_label = "EXPIRED"
        else:
            shift_label = shift.get("message") or f"error ({code})"
            layer = shift.get("layer")
    else:
        shift_label = "n/a (device closed)"
        layer = "LINK"

    last_failure = get_last_failure()
    if layer is None and last_failure:
        layer = last_failure.get("layer")

    flash = None
    if request.args.get("flash"):
        flash = {
            "kind": request.args.get("flash_kind", "ok"),
            "message": request.args.get("flash"),
        }

    diagnostics = None
    if request.args.get("diag") == "1":
        diagnostics = run_diagnostics_ladder()

    cfg = get_config()
    tax_type = cfg.get("tax_type")
    automatic_mode = normalize_automatic_mode(
        cfg.get("automatic_mode", False)
    )[0]
    machine_number = normalize_machine_number(cfg.get("machine_number", ""))[0]
    machine_numbers = normalize_machine_numbers_by_bay(
        cfg.get("machine_numbers_by_bay", {})
    )[0]
    return render_template(
        "admin/status.html",
        active="status",
        connection=connection,
        opened=bool(opened.get("opened")),
        shift_label=shift_label,
        layer=layer,
        layer_hint=next_action_for_layer(layer) if layer else None,
        last_failure=last_failure,
        queue=_queue_counts_today(),
        cashier_name=cfg.get("cashier_name") or "",
        send_cashier_to_kkt=normalize_send_cashier_to_kkt(
            cfg.get("send_cashier_to_kkt", True)
        )[0],
        automatic_mode=automatic_mode,
        machine_number=machine_number,
        machine_numbers=machine_numbers,
        tax_type_label=TAX_TYPE_LABELS.get(tax_type, f"Некорректно: {tax_type}"),
        flash=flash,
        diagnostics=diagnostics,
    )


@app.route("/admin/reconnect", methods=["POST"])
def admin_reconnect():
    """Status action: re-apply settings + open via CashierService."""
    busy = cashier_service.is_busy()
    result = cashier_service.apply_settings_and_reconnect(logger=app.logger)
    http_code = result.get("code", 500)
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        result["device_busy_at_request"] = busy
        return jsonify(result), http_code
    kind = "ok" if http_code == 200 else "err"
    msg = result.get("message", "Reconnect finished")
    if busy:
        msg = f"[was busy] {msg}"
        kind = "warn" if http_code == 200 else kind
    return redirect(
        url_for("admin_status", flash=msg, flash_kind=kind)
    )


@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    """Screen B — Settings (F-CFG-01–04, F-CONN-07)."""
    flash = None
    if request.method == "POST":
        action = request.form.get("action") or (
            (request.get_json(silent=True) or {}).get("action") if request.is_json else None
        ) or "save"

        if action == "reset":
            kept_key = get_config().get("monitoring_api_key") or ""
            cfg = reset_config()
            if kept_key:
                cfg = save_config({"monitoring_api_key": kept_key})
            flash = {"kind": "ok", "message": "Reset to defaults and saved."}
            if request.is_json or request.accept_mimetypes.best == "application/json":
                return jsonify({"code": 200, "config": _settings_view(cfg), "message": flash["message"]}), 200
            return render_template(
                "admin/settings.html",
                active="settings",
                cfg=_settings_view(cfg),
                device_busy=cashier_service.is_busy(),
                flash=flash,
            )

        data = _settings_from_request()
        errors = validate_settings_payload(data)
        if errors:
            body = {"code": 400, "errors": errors, "message": "; ".join(errors)}
            if request.is_json or request.accept_mimetypes.best == "application/json":
                return jsonify(body), 400
            return render_template(
                "admin/settings.html",
                active="settings",
                cfg=_settings_view({**get_config(), **{k: data.get(k, get_config().get(k)) for k in data}}),
                device_busy=cashier_service.is_busy(),
                flash={"kind": "err", "message": body["message"]},
            ), 400

        updates = coerce_settings_updates(data)
        cfg = save_config(updates)
        flash = {"kind": "ok", "message": "Settings saved."}
        reconnect_result = None
        if action == "save_reconnect":
            busy = cashier_service.is_busy()
            reconnect_result = cashier_service.apply_settings_and_reconnect(
                logger=app.logger
            )
            rc = reconnect_result.get("code", 500)
            if rc == 200:
                flash = {
                    "kind": "warn" if busy else "ok",
                    "message": (
                        f"Saved & reconnected"
                        f"{' (device was busy at request)' if busy else ''}."
                    ),
                }
            else:
                flash = {
                    "kind": "err",
                    "message": (
                        f"Saved, but reconnect failed: "
                        f"{reconnect_result.get('message')}"
                    ),
                }

        if request.is_json or request.accept_mimetypes.best == "application/json":
            payload = {"code": 200 if flash["kind"] != "err" else 500, "config": _settings_view(cfg), "message": flash["message"]}
            if reconnect_result is not None:
                payload["reconnect"] = reconnect_result
                payload["code"] = reconnect_result.get("code", payload["code"])
            return jsonify(payload), payload["code"]

        return render_template(
            "admin/settings.html",
            active="settings",
            cfg=_settings_view(cfg),
            device_busy=cashier_service.is_busy(),
            flash=flash,
        )

    return render_template(
        "admin/settings.html",
        active="settings",
        cfg=_settings_view(get_config()),
        device_busy=cashier_service.is_busy(),
        flash=flash,
    )


def _display_page(config, flash=None, status=200):
    recent = QRDisplayDelivery.query.order_by(QRDisplayDelivery.id.desc()).limit(20).all()
    return render_template("admin/displays.html", active="displays", groups=qr_displays.GROUPS,
                           displays=config, recent=recent, flash=flash), status


@app.route("/admin/displays", methods=["GET", "POST"])
def admin_displays():
    current = qr_displays.normalized_config(get_config().get("qr_displays", {}))
    wants_json = request.is_json or request.accept_mimetypes.best == "application/json"
    if request.method == "GET":
        if wants_json:
            return jsonify({"config": current})
        return _display_page(current)
    data = request.get_json(silent=True) if request.is_json else request.form
    if not isinstance(data, dict) and request.is_json:
        return jsonify({"code": 400, "errors": ["JSON должен быть объектом."]}), 400
    action = data.get("action")
    if action == "save_counts":
        counts = data.get("counts") if request.is_json else {
            key: data.get(f"count_{key}", current[key]["count"]) for key, _, _ in qr_displays.GROUPS
        }
        config, errors = qr_displays.save_counts(current, counts)
        if not errors:
            config, errors = qr_displays.save_addresses(config, {})
    elif action == "save_addresses":
        addresses = data.get("screens") if request.is_json else {
            key: {str(n): {"ip": data.get(f"ip_{key}_{n}", ""),
                            "port": data.get(f"port_{key}_{n}", "5001")}
                  for n in range(1, current[key]["count"] + 1)}
            for key, _, _ in qr_displays.GROUPS
        }
        config, errors = qr_displays.save_addresses(current, addresses)
    else:
        config, errors = current, ["Неизвестное действие."]
    if errors:
        if wants_json:
            return jsonify({"code": 400, "errors": errors}), 400
        return _display_page(current, {"kind": "err", "message": "; ".join(errors)}, 400)
    try:
        save_config({"qr_displays": config})
    except OSError:
        app.logger.exception("Cannot save QR display configuration")
        if wants_json:
            return jsonify({"code": 500, "message": "Не удалось сохранить настройки."}), 500
        return _display_page(current, {"kind": "err", "message": "Не удалось сохранить настройки."}, 500)
    message = "Сохранено. Новые адреса применяются без перезапуска."
    if wants_json:
        return jsonify({"code": 200, "config": config, "message": message})
    return redirect(url_for("admin_displays", saved="1"), code=303)


@app.route("/admin/displays/test", methods=["POST"])
def admin_display_test():
    data = request.get_json(silent=True) if request.is_json else request.form
    target = data.get("target", "") if isinstance(data, dict) or not request.is_json else ""
    parts = str(target).split(":")
    config = qr_displays.normalized_config(get_config().get("qr_displays", {}))
    address = qr_displays.endpoint(config, *parts) if len(parts) == 2 else None
    status, info = 200, None
    if not address:
        status, message = 400, "Сначала сохраните IP и TCP-порт этого экрана."
    else:
        try:
            with _qr_display_io_lock:
                address = qr_displays.endpoint(get_config().get("qr_displays", {}), *parts)
                if not address:
                    raise ValueError("Экран отключён или IP не назначен.")
                test_qr = "https://example.com/telemetron-test" if request.args.get("show_qr") == "1" else None
                info = qr_displays.communicate(*address, test_qr)
            message = ("Экран подтвердил тестовый QR. Проверьте его телефоном." if test_qr
                       else "Связь с Telemetron подтверждена.")
        except (OSError, ValueError) as exc:
            status, message = 502, str(exc)
    if request.is_json or request.accept_mimetypes.best == "application/json":
        return jsonify({"code": status, "message": message, "info": info}), status
    return _display_page(config, {"kind": "ok" if status == 200 else "err", "message": message}, status)


@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    """Screen C — Logs tail."""
    cfg = get_config()
    level = (request.args.get("level") or "").strip().upper() or None
    if level and level not in ("ERROR", "INFO"):
        level = None
    max_lines = int(cfg.get("max_log_lines") or 300)
    log_path = cfg.get("log_path") or LOG_PATH
    text_body, err = _tail_log_lines(log_path, max_lines, level)
    return render_template(
        "admin/logs.html",
        active="logs",
        log_path=log_path,
        max_lines=max_lines,
        level=level or "",
        log_text=text_body or "(empty)",
        log_error=err,
    )


@app.route("/admin/checks", methods=["GET"])
def admin_checks():
    """Screen D — recent checks list only (no retry — unsafe without anti-double-print)."""
    limit = request.args.get("limit", CHECK_HISTORY_LIMIT, type=int)
    limit = max(1, min(limit, CHECK_HISTORY_LIMIT))
    rows = Check.query.order_by(Check.id.desc()).limit(limit).all()
    return render_template(
        "admin/checks.html",
        active="checks",
        checks=[_check_to_dict(c) for c in rows],
    )


@app.route("/admin/diagnostics", methods=["GET", "POST"])
def admin_diagnostics():
    """
    F-DIAG-03..05: read-only ladder with per-step pass/fail + Where / What to do next.
    Browser form POST from Status redirects back; API clients get JSON.
    Unauthenticated — LAN trust MVP (see /admin note).
    """
    result = run_diagnostics_ladder()
    http_code = result.get("code", 500)
    if request.method == "POST" and request.mimetype in (
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    ):
        kind = "ok" if result.get("ok") else "err"
        msg = result.get("message") or (
            "Diagnostics OK" if result.get("ok") else "Diagnostics failed"
        )
        return redirect(url_for("admin_status", flash=msg, flash_kind=kind, diag="1"))
    return jsonify(result), http_code
