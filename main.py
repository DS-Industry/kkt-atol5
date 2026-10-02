from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from qr_images import register_qr_images, qr_image_url
from contextlib import contextmanager
from datetime import datetime, timedelta, date, timezone
import json
import math
import os
import sys
import threading
from flask_apscheduler import APScheduler

# Local Mac / no ATOL driver: MOCK_IFPTR=1 python3 main.py
# Must patch before cashierService constructs IFptr (same idea as tests/conftest.py).
if os.environ.get("MOCK_IFPTR") == "1":
    import libfptr10
    from tests.fake_fptr import build_fake_fptr_class

    libfptr10.IFptr = build_fake_fptr_class(libfptr10.IFptr)

from cashierService import cashier_service
import fiscal_report
from conf import (
    QR_WAIT_TIMEOUT_SEC,
    CHECK_RETENTION_DAYS,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    LOG_PATH,
    HTTP_HOST,
    HTTP_PORT,
    TAX_TYPE_LABELS,
    get_config,
    save_config,
    reset_config,
    validate_settings_payload,
    coerce_settings_updates,
    normalize_send_cashier_to_kkt,
    normalize_automatic_mode,
    normalize_machine_number,
    normalize_machine_numbers_by_bay,
    resolve_machine_number,
)
from fault_isolation import (
    build_failure_record,
    get_last_failure,
    map_error_to_layer,
    next_action_for_layer,
    remember_failure,
)
import time
import logging
from logging.handlers import RotatingFileHandler
from sqlalchemy import inspect, text

scheduler = APScheduler()
# Boot: one-shot open only — full F-CONN-04 backoff stays on fiscal paths
cashier_service.open_connection(max_attempts=1)
_log_path = get_config().get("log_path") or LOG_PATH
log_handler = RotatingFileHandler(
    _log_path,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
)
log_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
log_handler.setFormatter(formatter)

# Queue lifecycle (F-Q-01): pending → printing → done | failed
STATUS_PENDING = "pending"
STATUS_PRINTING = "printing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
CHECK_HISTORY_LIMIT = 10000
QR_POLL_INTERVAL_SEC = 5
MOSCOW_TIMEZONE = timezone(timedelta(hours=3), name="Europe/Moscow")

# Process-local waiter protection is sufficient because production is explicitly
# single-process (README: one HTTP + scheduler worker process). Counts support
# nested guards such as create-check guarding commit + find_actual_check guarding
# the wait itself.
_check_history_lock = threading.RLock()
_protected_check_id_counts = {}


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
                app.logger.info(f"Print check done: id={check.id}")
            except Exception as e:
                app.logger.error(
                    f"Error processing check {check.id}: {e}", exc_info=True
                )
                _mark_failed(check, str(e), context="queue", step="job1")
                db.session.commit()
                _queue_fiscal_outcome(check)
        _prune_checks_safely("queue cycle end")


app = Flask(__name__)

# Configure SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///checks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SCHEDULER_API_ENABLED'] = True
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

db = SQLAlchemy(app)


class Check(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    bay = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=True)
    quantity = db.Column(db.Integer, nullable=True)
    type = db.Column(db.String(50), nullable=False)
    sum = db.Column(db.Float, nullable=False)
    # Legacy flags kept during transition (AGENTS.md §6 / F-Q-01)
    isProcessed = db.Column(db.Boolean, default=False)
    isQr = db.Column(db.Boolean, default=False)
    dateCreated = db.Column(db.DateTime, default=datetime.utcnow)
    dateProcessed = db.Column(db.DateTime, nullable=True)
    qr = db.Column(db.String(255), nullable=True)
    fiscal_document = db.Column(db.Text, nullable=True)
    # Schema change (explicit): queue lifecycle + failure reason (Phase A)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    error_message = db.Column(db.String(500), nullable=True)
    error_code = db.Column(db.String(50), nullable=True)
    # Schema change (explicit, Phase B / F-DIAG-01, F-DIAG-07): fault isolation fields
    # ADDITIVE only — do not rename typo fields (quiantity/isProcessed/dateProccesed legacy).
    layer = db.Column(db.String(20), nullable=True)
    step = db.Column(db.String(50), nullable=True)
    error_description = db.Column(db.String(500), nullable=True)


class FiscalOutbox(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    payload = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


register_qr_images(app, db, Check)


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


def _ensure_schema():
    """
    create_all only (no drop_all — F-Q-03 / P3).
    SQLite create_all does not ADD columns to existing tables — ALTER missing ones.

    SCHEMA CHANGES (additive ALTER):
      Phase A: status, error_message, error_code
      Phase B: layer, step, error_description
    Never renames isProcessed / isQr / quantity (legacy contract).
    """
    db.create_all()
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    if "check" not in table_names:
        return

    existing = {col["name"] for col in inspector.get_columns("check")}
    alterations = []
    column_defs = [
        ("fiscal_document", "ALTER TABLE \"check\" ADD COLUMN fiscal_document TEXT"),
        ("status", "ALTER TABLE \"check\" ADD COLUMN status VARCHAR(20) DEFAULT 'pending'"),
        ("error_message", "ALTER TABLE \"check\" ADD COLUMN error_message VARCHAR(500)"),
        ("error_code", "ALTER TABLE \"check\" ADD COLUMN error_code VARCHAR(50)"),
        ("layer", "ALTER TABLE \"check\" ADD COLUMN layer VARCHAR(20)"),
        ("step", "ALTER TABLE \"check\" ADD COLUMN step VARCHAR(50)"),
        ("error_description", "ALTER TABLE \"check\" ADD COLUMN error_description VARCHAR(500)"),
    ]
    for col_name, stmt in column_defs:
        if col_name not in existing:
            alterations.append(stmt)

    with db.engine.begin() as conn:
        if alterations:
            for stmt in alterations:
                conn.execute(text(stmt))
            app.logger.info(
                "Applied Check schema alterations: %s",
                ", ".join(
                    c for c, _ in column_defs if c not in existing
                ),
            )
        # Backfill status from legacy flags (never leave processed rows as pending)
        conn.execute(text(
            "UPDATE \"check\" SET status = 'done' "
            "WHERE (status IS NULL OR status = 'pending') "
            "AND isProcessed = 1 AND isQr = 1"
        ))
        conn.execute(text(
            "UPDATE \"check\" SET status = 'failed', "
            "error_message = 'legacy pre-QR processed; not re-queued' "
            "WHERE (status IS NULL OR status = 'pending') "
            "AND isProcessed = 1 AND (isQr = 0 OR isQr IS NULL)"
        ))
        conn.execute(text(
            "UPDATE \"check\" SET status = 'pending' "
            "WHERE status IS NULL"
        ))


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


def run_diagnostics_ladder():
    """
    Read-only diagnostics ladder (F-DIAG-03..05). No sell receipt.
    Stop at first failure; return step + layer + Where / What to do next.
    """
    steps = []

    def _fail(step_num, name, layer, message, **extra):
        entry = {
            "step": step_num,
            "name": name,
            "pass": False,
            "layer": layer,
            "message": message,
            **extra,
        }
        steps.append(entry)
        where = layer
        return {
            "code": 503,
            "ok": False,
            "failed_step": step_num,
            "failed_name": name,
            "layer": layer,
            "where": where,
            "what_to_do_next": next_action_for_layer(layer),
            "steps": steps,
            "last_failure": get_last_failure(),
            "message": message,
        }

    # (1) app + DB
    try:
        db.session.execute(text("SELECT 1"))
        steps.append({"step": 1, "name": "app_db", "pass": True, "layer": "APP"})
    except Exception as e:
        app.logger.error("Diagnostics DB check failed: %s", e, exc_info=True)
        return _fail(1, "app_db", "APP", "Database check failed")

    # (2) library loadable
    lib = cashier_service.library_status()
    if lib.get("code") != 200 or not lib.get("loadable"):
        return _fail(
            2,
            "library",
            "APP",
            lib.get("message", "libfptr10 / IFptr not loadable"),
            detail=lib,
        )
    steps.append({"step": 2, "name": "library", "pass": True, "layer": "APP"})

    # (3) open / isOpened — single open attempt only (no full F-CONN-04 ladder)
    opened = cashier_service.is_device_opened()
    if not opened.get("opened"):
        recon = cashier_service.ensure_connected(
            logger=app.logger, max_attempts=1
        )
        if recon.get("code") != 200 or not recon.get("opened"):
            return _fail(
                3,
                "open",
                recon.get("layer", "LINK"),
                recon.get("message", "Device not opened"),
                error_code=recon.get("error_code"),
                error_description=recon.get("error_description"),
                detail=recon,
            )
    steps.append({"step": 3, "name": "open", "pass": True, "layer": "LINK"})

    # (4) shift status — no reconnect (already opened or one-shot above)
    shift = cashier_service.get_shift_status(reconnect=False)
    shift_code = shift.get("code")
    if shift_code not in (200, 400, 450):
        return _fail(
            4,
            "shift",
            shift.get("layer", "KKT"),
            shift.get("message", "get_shift_status failed"),
            error_code=shift.get("error_code"),
            detail=shift,
        )
    steps.append({
        "step": 4,
        "name": "shift",
        "pass": True,
        "layer": "KKT",
        "shift_code": shift_code,
        "shift": shift.get("shift"),
    })

    # (5) FN/OFD best-effort — no reconnect backoff
    fn_ofd = cashier_service.get_fn_ofd_status(reconnect=False)
    if fn_ofd.get("code") not in (200,):
        return _fail(
            5,
            "fn_ofd",
            fn_ofd.get("layer", "FN_OFD"),
            fn_ofd.get("message", "FN/OFD status query failed"),
            detail=fn_ofd,
        )
    steps.append({
        "step": 5,
        "name": "fn_ofd",
        "pass": True,
        "layer": "FN_OFD",
        "detail": {
            "fn": fn_ofd.get("fn"),
            "ofd": fn_ofd.get("ofd"),
            "errors": fn_ofd.get("errors"),
        },
    })

    return {
        "code": 200,
        "ok": True,
        "failed_step": None,
        "layer": None,
        "where": None,
        "what_to_do_next": "All diagnostics steps passed.",
        "steps": steps,
        "last_failure": get_last_failure(),
        "message": "Diagnostics OK",
    }


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


def _should_autostart_scheduler() -> bool:
    """
    Start job1 under the real process entrypoint (F-Q-07), including gunicorn/systemd
    import of main:app — not only `if __name__ == '__main__'`.
    Skip under pytest / DISABLE_SCHEDULER / Werkzeug reloader parent.
    Under reloader: only when WERKZEUG_RUN_MAIN == "true" (child).
    """
    if os.environ.get("DISABLE_SCHEDULER") == "1":
        return False
    if app.config.get("TESTING"):
        return False
    if "pytest" in sys.modules:
        return False
    # Werkzeug debug reloader child
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return True
    # Reloader parent (or any non-true RUN_MAIN): do not start
    if "WERKZEUG_RUN_MAIN" in os.environ:
        return False
    # WSGI import (gunicorn/systemd): module is not __main__
    if __name__ != "__main__":
        return True
    # `python main.py` parent before reloader — defer to __main__ block
    return False


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


def start_scheduler():
    """Idempotent APScheduler start for job1 (F-Q-07)."""
    if getattr(app, "_apscheduler_started", False):
        return
    if scheduler.running:
        app._apscheduler_started = True
        return
    scheduler.init_app(app)
    scheduler.start()
    app._apscheduler_started = True
    app.logger.info("APScheduler started (job1 interval print worker)")


def _is_test_runtime():
    """Detect pytest/import-time test mode before fixtures can set TESTING."""
    return bool(app.config.get("TESTING")) or "pytest" in sys.modules


def _initialize_database_at_startup():
    """Create/add schema on boot; prune production history only."""
    with app.app_context():
        # P3 / F-Q-03: never wipe DB on boot
        _ensure_schema()
        # Tests rebind SQLAlchemy after importing this module. Never prune the
        # default instance/checks.db before that fixture has installed temp DB.
        if not _is_test_runtime():
            _prune_checks_safely("startup")


_initialize_database_at_startup()

app.logger.info("The program has started!")

# F-Q-07: start scheduler for production import path (systemd/gunicorn main:app)
if _should_autostart_scheduler():
    start_scheduler()

if __name__ == '__main__':
    # Non-reloader script run: start here (import path skipped when __name__==__main__).
    # Reloader child already started via WERKZEUG_RUN_MAIN=="true" above.
    if _should_autostart_scheduler() or "WERKZEUG_RUN_MAIN" not in os.environ:
        start_scheduler()
    cfg = get_config()
    host = cfg.get("http_host") or HTTP_HOST
    port = int(cfg.get("http_port") or HTTP_PORT)
    app.run(host=host, port=port)
