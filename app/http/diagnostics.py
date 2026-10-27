"""Read-only diagnostics ladder. Does not sell a receipt."""
from sqlalchemy import text

from app.runtime import app, db
from app.services.cashier import cashier_service
from app.services.faults import get_last_failure, next_action_for_layer


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
