import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

# Local Mac / no ATOL driver: MOCK_IFPTR=1 python3 main.py
# Must patch before cashier constructs IFptr (same idea as tests/conftest.py).
if os.environ.get("MOCK_IFPTR") == "1":
    import libfptr10
    from tests.fake_fptr import build_fake_fptr_class

    libfptr10.IFptr = build_fake_fptr_class(libfptr10.IFptr)

from app.data.config import (
    HTTP_HOST,
    HTTP_PORT,
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    LOG_PATH,
    get_config,
)
from app.data.models import Check, FiscalOutbox, QRDisplayDelivery
from app.data.schema import _ensure_schema
from app.runtime import app, db, scheduler
from app.services.cashier import cashier_service
from app.services.qr_images import register_qr_images
from app.services.queue import (
    CHECK_HISTORY_LIMIT,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PRINTING,
    _check_to_dict,
    _device_snapshot,
    _ensure_shift_ready,
    _mark_failed,
    _protected_check_id_counts,
    _prune_checks_safely,
    _prune_checks_to_limit,
    _queue_qr_display,
    find_actual_check,
    flush_fiscal_outbox,
    flush_qr_displays,
    job1,
)
from app.http import admin as admin_routes  # noqa: F401  (register /admin routes)
from app.http import api as api_routes  # noqa: F401  (register POS routes)

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
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

register_qr_images(app, db, Check)


def _should_autostart_scheduler() -> bool:
    """
    Start job1 under the real process entrypoint (F-Q-07).
    Supervisor runs `python3 main.py`, so the __main__ block starts the scheduler.
    A gunicorn/WSGI import of main:app starts it on import.
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
    # WSGI import (gunicorn): module is not __main__
    if __name__ != "__main__":
        return True
    # `python main.py` parent before reloader — defer to __main__ block
    return False


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

# F-Q-07: start scheduler when this module is imported (gunicorn main:app).
# supervisorctl runs `python3 main.py`, which starts the scheduler below.
if _should_autostart_scheduler():
    start_scheduler()

if __name__ == "__main__":
    # Non-reloader script run: start here (import path skipped when __name__==__main__).
    # Reloader child already started via WERKZEUG_RUN_MAIN=="true" above.
    if _should_autostart_scheduler() or "WERKZEUG_RUN_MAIN" not in os.environ:
        start_scheduler()
    cfg = get_config()
    host = cfg.get("http_host") or HTTP_HOST
    port = int(cfg.get("http_port") or HTTP_PORT)
    app.run(host=host, port=port)
