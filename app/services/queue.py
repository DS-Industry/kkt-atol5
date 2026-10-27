"""Print queue, QR wait, history cleanup, and delivery outboxes."""
import json
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import app.services.fiscal_report as fiscal_report
import app.services.qr_displays as qr_displays
from app.data.config import CHECK_RETENTION_DAYS, QR_WAIT_TIMEOUT_SEC, get_config
from app.data.models import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PRINTING,
    Check,
    FiscalOutbox,
    QRDisplayDelivery,
)
from app.runtime import app, db, scheduler
from app.services.cashier import cashier_service
from app.services.faults import (
    build_failure_record,
    map_error_to_layer,
    next_action_for_layer,
    remember_failure,
)
from app.services.qr_images import qr_image_url

# Queue lifecycle (F-Q-01): pending → printing → done | failed
CHECK_HISTORY_LIMIT = 10000
QR_POLL_INTERVAL_SEC = 5
MOSCOW_TIMEZONE = timezone(timedelta(hours=3), name="Europe/Moscow")

# Process-local waiter protection is sufficient because production is explicitly
# single-process (README: one HTTP + scheduler worker process). Counts support
# nested guards such as create-check guarding commit + find_actual_check guarding
# the wait itself.
_check_history_lock = threading.RLock()
_protected_check_id_counts = {}
_qr_display_io_lock = threading.Lock()


def _register_protected_check_id(check_id):
    """Register one live QR waiter and return its normalized database id."""
    normalized_id = int(check_id)
    with _check_history_lock:
        _protected_check_id_counts[normalized_id] = (
            _protected_check_id_counts.get(normalized_id, 0) + 1
        )
    return normalized_id


def _unregister_protected_check_id(check_id):
    """Release one waiter registration without disturbing nested waiters."""
    normalized_id = int(check_id)
    with _check_history_lock:
        remaining = _protected_check_id_counts.get(normalized_id, 0) - 1
        if remaining > 0:
            _protected_check_id_counts[normalized_id] = remaining
        else:
            _protected_check_id_counts.pop(normalized_id, None)


@contextmanager
def _protect_check_id(check_id):
    """Keep a check outside pruning for the duration of a live QR wait."""
    normalized_id = _register_protected_check_id(check_id)
    try:
        yield normalized_id
    finally:
        _unregister_protected_check_id(normalized_id)


@contextmanager
def _flush_and_protect_new_check(check):
    """Allocate an id and protect it before its transaction becomes visible."""
    # Pruning uses lock → DB ordering too. Taking the lock before flush avoids
    # an SQLite writer/history-lock inversion while closing the visibility race.
    with _check_history_lock:
        db.session.flush()
        normalized_id = _register_protected_check_id(check.id)
    try:
        yield normalized_id
    finally:
        _unregister_protected_check_id(normalized_id)


def _mark_failed(check, message, error_code=None, *, step=None, layer=None,
                 error_description=None, context=None):
    """Terminal fail: store F-DIAG-01 fields including layer (F-DIAG-07)."""
    resolved_layer = layer or map_error_to_layer(
        error_code, step=step, context=context
    )
    check.status = STATUS_FAILED
    check.error_message = (message or "")[:500]
    check.error_code = str(error_code) if error_code is not None else None
    check.error_description = (error_description or message or "")[:500] or None
    check.layer = resolved_layer
    check.step = (step or "")[:50] or None
    check.dateProcessed = datetime.utcnow()
    remember_failure(
        build_failure_record(
            layer=resolved_layer,
            step=step,
            error_code=error_code,
            error_description=error_description or message,
            check_id=getattr(check, "id", None),
            message=message,
        )
    )
    # Do not set isProcessed/isQr on failure — success flags only after print+QR (F-Q-02)


def _requeue_pending(check, message, error_code=None, *, step=None, layer=None):
    """Revert printing → pending on retryable shift timeouts (P4). Never leave stuck printing."""
    check.status = STATUS_PENDING
    check.error_message = (message or "")[:500]
    check.error_code = str(error_code) if error_code is not None else None
    if layer:
        check.layer = layer
    if step:
        check.step = step[:50]


def _ensure_shift_ready(app):
    """Require OPEN shift; close EXPIRED then open; open if CLOSED. Honors open/close timeouts."""
    shift_status = cashier_service.get_shift_status()
    code = shift_status.get("code")
    if code == 200:
        return {"code": 200}
    if code == 450:
        close_res = cashier_service.close_shift()
        if close_res.get("code") not in (200, 201):
            return close_res
        return cashier_service.openShift()
    if code == 400:
        return cashier_service.openShift()
    return shift_status


@scheduler.task("interval", id="do_job_1", seconds=3, misfire_grace_time=900, max_instances=1)
def job1():
    with app.app_context():
        _prune_checks_safely("queue cycle start")
        # Only pending jobs; device lock serializes concurrent prints (F-Q-08)
        checks = (
            Check.query.filter_by(status=STATUS_PENDING)
            .order_by(Check.id.asc())
            .all()
        )
        for check in checks:
            check.status = STATUS_PRINTING
            db.session.commit()
            app.logger.info(f"Printing check: id={check.id}")

            try:
                shift_ready = _ensure_shift_ready(app)
                if shift_ready.get("code") != 200:
                    # 504 / retryable shift open|close timeout → re-queue, do not permanent-fail
                    if shift_ready.get("code") == 504 or shift_ready.get("retryable"):
                        _requeue_pending(
                            check,
                            shift_ready.get("message", "Shift timed out"),
                            shift_ready.get("error_code"),
                            step=shift_ready.get("step"),
                            layer=shift_ready.get("layer"),
                        )
                        db.session.commit()
                        app.logger.warning(
                            "Shift timeout for check %s (re-queued pending): %s",
                            check.id,
                            shift_ready,
                        )
                        continue
                    _mark_failed(
                        check,
                        shift_ready.get("message", "Shift not ready"),
                        shift_ready.get("error_code"),
                        step=shift_ready.get("step") or "shift",
                        layer=shift_ready.get("layer"),
                        error_description=shift_ready.get("error_description"),
                    )
                    db.session.commit()
                    _queue_fiscal_outcome(check)
                    app.logger.error(
                        "Shift not ready for check %s: %s", check.id, shift_ready
                    )
                    continue

                check_data = {
                    "id": check.id,
                    "name": check.name,
                    "bay": check.bay,
                    "price": check.sum,
                    "sum": check.sum,
                    "quiantity": 1,
                    "type": check.type,
                }
                print_result = cashier_service.print_check(check_data, app)
                if print_result.get("code") != 201:
                    _mark_failed(
                        check,
                        print_result.get("message", "print_check failed"),
                        print_result.get("error_code"),
                        step=print_result.get("step"),
                        layer=print_result.get("layer"),
                        error_description=print_result.get("error_description"),
                    )
                    db.session.commit()
                    _queue_fiscal_outcome(check)
                    app.logger.error(
                        "Print failed for check %s: %s", check.id, print_result
                    )
                    continue

                result = cashier_service.readLastReciept()
                if isinstance(result, dict) and result.get("code") not in (None, 200, 201):
                    _mark_failed(
                        check,
                        result.get("message", "Failed to read last receipt"),
                        result.get("error_code"),
                        step=result.get("step") or "readLastReciept",
                        layer=result.get("layer"),
                        error_description=result.get("error_description"),
                    )
                    db.session.commit()
                    _queue_fiscal_outcome(check)
                    continue

                text_payload = result.strip().strip('"')
                data = json.loads(text_payload)
                qr = data["documentTLV"]["qr"]

                check.qr = qr
                # Keep the exact FN response with this receipt, never reconstruct it
                # later from mutable application settings or a different last receipt.
                check.fiscal_document = json.dumps(data, ensure_ascii=False)
                check.isQr = True
                check.isProcessed = True
                check.status = STATUS_DONE
                check.dateProcessed = datetime.utcnow()
                check.error_message = None
                check.error_code = None
                check.error_description = None
                check.layer = None
                check.step = None
                db.session.commit()
                _queue_fiscal_outcome(check)
                _queue_qr_display(check)
                app.logger.info(f"Print check done: id={check.id}")
            except Exception as e:
                app.logger.error(
                    f"Error processing check {check.id}: {e}", exc_info=True
                )
                _mark_failed(check, str(e), context="queue", step="job1")
                db.session.commit()
                _queue_fiscal_outcome(check)
        _prune_checks_safely("queue cycle end")

def _queue_qr_display(check):
    """A screen failure must never requeue or fail an already fiscalized receipt."""
    try:
        category = qr_displays.category_for_name(check.name)
        cfg = get_config().get("qr_displays", {})
        if check.status != STATUS_DONE or not check.qr or not qr_displays.endpoint(cfg, category, check.bay):
            return
        if QRDisplayDelivery.query.filter_by(check_id=check.id).first():
            return
        bay = str(int(check.bay))
        QRDisplayDelivery.query.filter(
            QRDisplayDelivery.category == category,
            QRDisplayDelivery.bay == bay,
            QRDisplayDelivery.status == "pending",
            QRDisplayDelivery.check_id < check.id,
        ).update({"status": "superseded"}, synchronize_session=False)
        db.session.add(QRDisplayDelivery(
            check_id=check.id, category=category, bay=bay, qr=check.qr,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("QR display queue failed for check %s", check.id)


def flush_qr_displays():
    now = datetime.utcnow()
    rows = (QRDisplayDelivery.query.filter_by(status="pending")
            .filter(QRDisplayDelivery.next_attempt_at <= now)
            .order_by(QRDisplayDelivery.check_id.asc()).limit(5).all())
    for row in rows:
        newer = QRDisplayDelivery.query.filter(
            QRDisplayDelivery.category == row.category,
            QRDisplayDelivery.bay == row.bay,
            QRDisplayDelivery.check_id > row.check_id,
        ).first()
        if newer:
            row.status = "superseded"
            db.session.commit()
            continue
        # Resolve the live mapping for every delivery, including retries.
        try:
            with _qr_display_io_lock:
                address = qr_displays.endpoint(get_config().get("qr_displays", {}), row.category, row.bay)
                if address:
                    row.attempts += 1
                    row.host = f"{address[0]}:{address[1]}"
                    qr_displays.communicate(*address, row.qr)
                    row.status = "sent"
                    row.error = None
                else:
                    row.status = "skipped"
                    row.error = "Экран отключён или IP не назначен."
        except (OSError, ValueError) as exc:
            row.error = str(exc)[:500]
            row.status = "failed" if row.attempts >= 3 else "pending"
            row.next_attempt_at = datetime.utcnow() + timedelta(seconds=5 * row.attempts)
            app.logger.warning("QR screen delivery failed for check %s: %s", row.check_id, row.error)
        db.session.commit()
    # Keep a bounded operational history, independently of the fiscal check table.
    old = (QRDisplayDelivery.query.filter(QRDisplayDelivery.status != "pending")
           .order_by(QRDisplayDelivery.id.desc()).offset(1000).limit(500).all())
    for row in old:
        db.session.delete(row)
    if old:
        db.session.commit()


def _configured_pos_id(cfg):
    raw = cfg.get("monitoring_pos_id")
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _device_snapshot():
    opened = cashier_service.is_device_opened()
    shift = cashier_service.get_shift_status(reconnect=False)
    fn_ofd = cashier_service.get_fn_ofd_status(reconnect=False)
    fn_body = fn_ofd.get("fn") or {}
    ofd_body = fn_ofd.get("ofd") or {}
    count = ofd_body.get("documents_count") if "documents_count" in ofd_body else None
    return {
        "treasurerLinkOpen": opened.get("opened") if "opened" in opened else None,
        "shiftStatus": shift.get("shift"),
        "fnMemoryOverflow": fn_body.get("memory_overflow"),
        "fnResourceExhausted": fn_body.get("resource_exhausted"),
        "fnReplacementRequired": fn_body.get("need_replacement"),
        "ofdUnsentDocumentsCount": count,
    }


def _queue_fiscal_outcome(check):
    try:
        if check.status not in (STATUS_DONE, STATUS_FAILED):
            return
        cfg = get_config()
        base_url = (cfg.get("monitoring_url") or "").strip()
        api_key = (cfg.get("monitoring_api_key") or "").strip()
        pos_id = _configured_pos_id(cfg)
        if not base_url or not api_key or pos_id is None:
            return
        if FiscalOutbox.query.filter_by(check_id=check.id).first() is not None:
            return
        snapshot = _device_snapshot()
        packet, missing = fiscal_report.build_packet(
            {
                "status": check.status,
                "name": check.name,
                "type": check.type,
                "sum": check.sum,
                "qr": check.qr,
                "fiscal_document": check.fiscal_document,
                "step": check.step,
                "error_code": check.error_code,
                "error_text": check.error_description or check.error_message,
            },
            snapshot,
            pos_id,
        )
        if packet is None:
            app.logger.warning(
                "fiscal monitor skipped for check %s, missing %s",
                check.id,
                ", ".join(missing),
            )
            return
        db.session.add(
            FiscalOutbox(
                check_id=check.id,
                payload=json.dumps(packet, ensure_ascii=False),
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "fiscal monitor queue failed for check %s",
            getattr(check, "id", None),
        )


def flush_fiscal_outbox():
    cfg = get_config()
    base_url = (cfg.get("monitoring_url") or "").strip()
    api_key = (cfg.get("monitoring_api_key") or "").strip()
    if not base_url or not api_key:
        return
    rows = FiscalOutbox.query.order_by(FiscalOutbox.id.asc()).all()
    for row in rows:
        try:
            body = json.loads(row.payload)
        except json.JSONDecodeError:
            app.logger.warning("fiscal monitor dropped unreadable outbox %s", row.id)
            db.session.delete(row)
            db.session.commit()
            continue
        if not fiscal_report.deliver(base_url, api_key, body):
            app.logger.warning("fiscal monitor delivery failed for outbox %s", row.id)
            return
        db.session.delete(row)
        db.session.commit()

def cleanup_old_checks(retention_days=None):
    """
    Optional soft-retain cleanup (F-Q-06). Deletes done|failed older than retention.
    No Admin GUI — call manually or from ops cron.
    """
    if retention_days is None:
        retention_days = get_config().get("check_retention_days") or CHECK_RETENTION_DAYS
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    with _check_history_lock:
        cleanup_query = Check.query.filter(
            Check.status.in_([STATUS_DONE, STATUS_FAILED]),
            Check.dateProcessed.isnot(None),
            Check.dateProcessed < cutoff,
        )
        protected_ids = tuple(_protected_check_id_counts)
        if protected_ids:
            cleanup_query = cleanup_query.filter(Check.id.notin_(protected_ids))
        deleted = cleanup_query.delete(synchronize_session=False)
        db.session.commit()
    return {"deleted": deleted, "retention_days": retention_days, "cutoff": cutoff.isoformat()}


def _prune_checks_to_limit(limit=CHECK_HISTORY_LIMIT):
    """
    Keep at most ``limit`` rows when terminal history can be removed safely.

    Pending/printing rows are never deletion candidates. If active rows alone
    make the table exceed the limit, the temporary overflow is retained.
    """
    # The same lock serializes waiter registration with candidate selection and
    # deletion. A waiter registered before its row becomes visible therefore
    # cannot lose the row even if the wall clock jumps far forward.
    with _check_history_lock:
        total = db.session.query(db.func.count(Check.id)).scalar() or 0
        excess = max(total - limit, 0)
        if excess == 0:
            return 0

        wait_timeout_sec = (
            get_config().get("qr_wait_timeout_sec") or QR_WAIT_TIMEOUT_SEC
        )
        prune_before = datetime.utcnow() - timedelta(
            seconds=float(wait_timeout_sec) + QR_POLL_INTERVAL_SEC
        )
        prunable_terminal = (
            Check.dateProcessed.is_(None)
            | (Check.dateProcessed < prune_before)
        )

        protected_ids = tuple(_protected_check_id_counts)
        candidates = db.session.query(Check.id).filter(
            Check.status.in_([STATUS_DONE, STATUS_FAILED]),
            # NULL is legacy terminal history with no live waiter timestamp.
            prunable_terminal,
        )
        if protected_ids:
            candidates = candidates.filter(Check.id.notin_(protected_ids))

        terminal_ids = [
            row[0]
            for row in (
                candidates.order_by(Check.id.asc()).limit(excess).all()
            )
        ]
        if not terminal_ids:
            return 0

        # Repeat state, age, and live-waiter exclusions in DELETE. The lock is
        # deliberately held through commit, eliminating a select/delete window
        # in which another thread could register one of these ids.
        delete_query = Check.query.filter(
            Check.id.in_(terminal_ids),
            Check.status.in_([STATUS_DONE, STATUS_FAILED]),
            prunable_terminal,
        )
        protected_ids = tuple(_protected_check_id_counts)
        if protected_ids:
            delete_query = delete_query.filter(Check.id.notin_(protected_ids))
        deleted = delete_query.delete(synchronize_session=False)
        db.session.commit()
        app.logger.info(
            "Pruned %s oldest terminal check(s); history limit=%s",
            deleted,
            limit,
        )
        return deleted


def _prune_checks_safely(context):
    """Best-effort runtime pruning without disrupting receipt processing."""
    try:
        return _prune_checks_to_limit()
    except Exception:
        db.session.rollback()
        app.logger.error(
            "Failed to prune check history during %s", context, exc_info=True
        )
        return 0


def _utc_iso(value):
    """Serialize a stored UTC datetime as an unambiguous ISO-8601 string."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _moscow_datetime_display(value):
    """Format a stored UTC datetime for the Orange Pi's Moscow-time UI."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MOSCOW_TIMEZONE).strftime("%d.%m.%Y %H:%M:%S")


def find_actual_check(name_value, check_id=None, timeout_sec=None):
    """
    Wait for QR with hard timeout (F-Q-05 / AC-4). Prefer check id (F-Q-04).
    Soft-retain on success — do NOT delete the row (F-Q-06 / P6).
    Name-only polls must not accept soft-retained historical QR for the same
    bay/name — resolve to pending/printing id, or require id > wait-start floor.
    Returns dict: {code, qr?, id?, status?} for HTTP mapping.
    """
    protected_id = None

    def protect_resolved_id(resolved_id):
        nonlocal protected_id
        normalized_id = int(resolved_id)
        if protected_id == normalized_id:
            return
        # Name-only resolution calls this while holding the same RLock, so
        # switching protection remains atomic relative to pruning.
        with _check_history_lock:
            previous_id = protected_id
            protected_id = _register_protected_check_id(normalized_id)
            if previous_id is not None:
                _unregister_protected_check_id(previous_id)

    if check_id is not None:
        protect_resolved_id(check_id)

    try:
        return _find_actual_check(
            name_value,
            check_id=check_id,
            timeout_sec=timeout_sec,
            protect_resolved_id=protect_resolved_id,
        )
    finally:
        if protected_id is not None:
            _unregister_protected_check_id(protected_id)


def _find_actual_check(
    name_value, check_id=None, timeout_sec=None, *, protect_resolved_id
):
    """Implementation for find_actual_check; the public wrapper owns guards."""
    if timeout_sec is None:
        timeout_sec = get_config().get("qr_wait_timeout_sec") or QR_WAIT_TIMEOUT_SEC
    deadline = time.monotonic() + timeout_sec

    # Resolve wait target once so soft-retained done rows cannot satisfy a new wait
    effective_id = check_id
    id_floor = None
    if effective_id is None and name_value:
        with _check_history_lock:
            active = (
                Check.query.filter(
                    Check.name == name_value,
                    Check.status.in_([STATUS_PENDING, STATUS_PRINTING]),
                )
                .order_by(Check.id.desc())
                .first()
            )
            if active is not None:
                effective_id = active.id
                protect_resolved_id(effective_id)
            else:
                # Ignore any QR/failed rows that already existed when the wait began
                id_floor = db.session.query(db.func.max(Check.id)).scalar() or 0

    while time.monotonic() < deadline:
        time.sleep(QR_POLL_INTERVAL_SEC)
        db.session.rollback()

        if effective_id is None and name_value and id_floor is not None:
            with _check_history_lock:
                active = (
                    Check.query.filter(
                        Check.name == name_value,
                        Check.status.in_([STATUS_PENDING, STATUS_PRINTING]),
                        Check.id > id_floor,
                    )
                    .order_by(Check.id.desc())
                    .first()
                )
                if active is not None:
                    effective_id = active.id
                    protect_resolved_id(effective_id)
                else:
                    # Job may have finished between polls — only accept post-floor rows
                    check = (
                        Check.query.filter(
                            Check.name == name_value,
                            Check.isQr.is_(True),
                            Check.qr.isnot(None),
                            Check.id > id_floor,
                        )
                        .order_by(Check.id.desc())
                        .first()
                    )
                    if check:
                        return {
                            "code": 201,
                            "qr": check.qr,
                            "qrGenerated": bool(check.isQr),
                            "dateTime": _utc_iso(check.dateCreated),
                            "id": check.id,
                            "status": check.status,
                        }
                    failed = (
                        Check.query.filter(
                            Check.name == name_value,
                            Check.status == STATUS_FAILED,
                            Check.id > id_floor,
                        )
                        .order_by(Check.id.desc())
                        .first()
                    )
                    if failed:
                        return {
                            "code": 502,
                            "message": failed.error_message or "Print failed",
                            "error_code": failed.error_code,
                            "error_description": failed.error_description,
                            "layer": failed.layer,
                            "step": failed.step,
                            "id": failed.id,
                            "status": failed.status,
                            "where": failed.layer,
                            "what_to_do_next": next_action_for_layer(failed.layer)
                            if failed.layer
                            else None,
                        }
            if effective_id is None:
                continue

        if effective_id is not None:
            check = db.session.get(Check, effective_id)
            if check is None:
                return {"code": 404, "message": "Check not found", "id": effective_id}
            if check.status == STATUS_FAILED:
                return {
                    "code": 502,
                    "message": check.error_message or "Print failed",
                    "error_code": check.error_code,
                    "error_description": check.error_description,
                    "layer": check.layer,
                    "step": check.step,
                    "id": check.id,
                    "status": check.status,
                    "where": check.layer,
                    "what_to_do_next": next_action_for_layer(check.layer)
                    if check.layer
                    else None,
                }
            if check.isQr and check.qr:
                # F-Q-06: soft-retain — keep row for audit; do not delete
                return {
                    "code": 201,
                    "qr": check.qr,
                    "qrGenerated": bool(check.isQr),
                    "dateTime": _utc_iso(check.dateCreated),
                    "id": check.id,
                    "status": check.status,
                }

    body = {
        "code": 504,
        "message": f"QR wait timed out after {timeout_sec}s",
        "retryable": True,
        "status": STATUS_PRINTING,
        "layer": "APP",
        "where": "APP",
        "what_to_do_next": next_action_for_layer("APP"),
    }
    if effective_id is not None:
        body["id"] = effective_id
        check = db.session.get(Check, effective_id)
        if check:
            body["status"] = check.status
    elif name_value:
        # Best-effort id for legacy callers (newest row for name, preferably active)
        with _check_history_lock:
            pending = (
                Check.query.filter_by(name=name_value)
                .order_by(Check.id.desc())
                .first()
            )
            if pending:
                body["id"] = pending.id
                body["status"] = pending.status
    return body


def _check_to_dict(check):
    return {
        "id": check.id,
        "name": check.name,
        "bay": check.bay,
        "price": check.price,
        "quantity": check.quantity,
        "type": check.type,
        "sum": check.sum,
        "isProcessed": check.isProcessed,
        "dateCreated": check.dateCreated,
        "dateProcessed": check.dateProcessed,
        "dateTime": _utc_iso(check.dateCreated),
        "dateTimeDisplay": _moscow_datetime_display(check.dateCreated),
        "qr": check.qr,
        "qrImageUrl": qr_image_url(check.id, check.qr)
        if check.status == STATUS_DONE and check.isQr and check.qr else None,
        "isQr": check.isQr,
        "qrGenerated": bool(check.isQr),
        "status": check.status,
        "error_message": check.error_message,
        "error_code": check.error_code,
        "error_description": check.error_description,
        "layer": check.layer,
        "step": check.step,
    }


def _queue_counts_today():
    """Pending/printing are live; failed/done counted for UTC calendar today."""
    today_start = datetime.combine(date.today(), datetime.min.time())
    pending = Check.query.filter_by(status=STATUS_PENDING).count()
    printing = Check.query.filter_by(status=STATUS_PRINTING).count()
    failed = Check.query.filter(
        Check.status == STATUS_FAILED,
        Check.dateProcessed >= today_start,
    ).count()
    done = Check.query.filter(
        Check.status == STATUS_DONE,
        Check.dateProcessed >= today_start,
    ).count()
    return {
        "pending": pending,
        "printing": printing,
        "failed": failed,
        "done": done,
        "as_of": "today_utc",
    }

@scheduler.task(
    "interval",
    id="flush_fiscal_outbox",
    seconds=5,
    misfire_grace_time=30,
    max_instances=1,
)
def flush_fiscal_outbox_job():
    with app.app_context():
        flush_fiscal_outbox()


@scheduler.task("interval", id="flush_qr_displays", seconds=3, misfire_grace_time=30, max_instances=1)
def flush_qr_displays_job():
    with app.app_context():
        try:
            flush_qr_displays()
        except Exception:
            db.session.rollback()
            app.logger.exception("QR display worker failed")
