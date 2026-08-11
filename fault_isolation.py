"""
Fault layer mapping for tech support (FSD §5.8 / F-DIAG-01..02, F-DIAG-04, F-DIAG-07).

Layers: APP | LINK | KKT | FN_OFD | HW_ENV | UNKNOWN
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

# Layer codes (FSD §5.8)
LAYER_APP = "APP"
LAYER_LINK = "LINK"
LAYER_KKT = "KKT"
LAYER_FN_OFD = "FN_OFD"
LAYER_HW_ENV = "HW_ENV"
LAYER_UNKNOWN = "UNKNOWN"

# ATOL error codes (libfptr10 / #error_list) — keep numeric so mapping works without IFptr import
_ERROR_PORT_NOT_AVAILABLE = 4
_ERROR_NO_CONNECTION = 2
_ERROR_CONNECTION_DISABLED = 1
_ERROR_PORT_BUSY = 3
_ERROR_CONNECTION_LOST = 241
_ERROR_FN_NO_MORE_DATA = 123
_ERROR_FISCAL_MEMORY_OVERFLOW = 70
_ERROR_NO_PAPER = 44
_ERROR_COVER_OPENED = 45
_ERROR_BUSY = 55
_ERROR_SHIFT_EXPIRED = 68
_ERROR_PRINTER_FAULT = 46
_ERROR_MECHANICAL_FAULT = 47

_LINK_CODES = frozenset(
    {
        _ERROR_CONNECTION_DISABLED,
        _ERROR_NO_CONNECTION,
        _ERROR_PORT_BUSY,
        _ERROR_PORT_NOT_AVAILABLE,
        _ERROR_CONNECTION_LOST,
    }
)

_FN_OFD_CODES = frozenset(
    {
        _ERROR_FN_NO_MORE_DATA,
        _ERROR_FISCAL_MEMORY_OVERFLOW,
    }
)

_KKT_CODES = frozenset(
    {
        _ERROR_NO_PAPER,
        _ERROR_COVER_OPENED,
        _ERROR_BUSY,
        _ERROR_SHIFT_EXPIRED,
        _ERROR_PRINTER_FAULT,
        _ERROR_MECHANICAL_FAULT,
    }
)

_NEXT_ACTIONS = {
    LAYER_APP: "Restart the service on the Orange Pi; check SQLite/queue and app logs.",
    LAYER_LINK: (
        "Check USB cable/power and usbcore.autosuspend=-1 "
        "(see docs/ops-runbook.md); retry open/reconnect."
    ),
    LAYER_KKT: "Check KKT shift state, paper, cover; service or replace the register if persistent.",
    LAYER_FN_OFD: (
        "Inspect FN/OFD settings and operator portal; FN memory/OFD exchange "
        "is not fixed by restarting Flask alone."
    ),
    LAYER_HW_ENV: "Check PSU/overheat under load; stabilize 3.3–3.5 V supply before blaming software.",
    LAYER_UNKNOWN: "Run /admin/diagnostics and attach the JSON result for support.",
}

# In-memory last failure for health/diagnostics when no check row is involved
_last_failure: Optional[dict[str, Any]] = None


def map_error_to_layer(
    error_code: Any = None,
    *,
    step: Optional[str] = None,
    context: Optional[str] = None,
    override: Optional[str] = None,
) -> str:
    """
    Map ATOL / field signals to a fault layer (F-DIAG-02).
    `override` wins when callers know context better (e.g. open failed → LINK).
    """
    if override:
        return override

    if context in (
        "db",
        "schema",
        "validation",
        "timeout_qr",
        "timeout_app",
        "queue",
    ):
        return LAYER_APP
    if context in ("reconnect", "open", "isOpened", "port_unavailable", "usb"):
        return LAYER_LINK
    if context in ("fn", "ofd", "fn_ofd"):
        return LAYER_FN_OFD
    if context in ("psu", "overheat", "hw_env"):
        return LAYER_HW_ENV

    try:
        code = int(error_code) if error_code is not None and error_code != "" else None
    except (TypeError, ValueError):
        code = None

    if code in _LINK_CODES:
        return LAYER_LINK
    if code in _FN_OFD_CODES:
        return LAYER_FN_OFD
    if code in _KKT_CODES:
        return LAYER_KKT

    # Connection steps without a mapped code still default to LINK
    if step in ("open", "open_connection", "reconnect", "isOpened"):
        return LAYER_LINK

    # Fiscal/shift steps with unknown nonzero code → KKT (device opened path)
    if step in (
        "openReceipt",
        "registration",
        "payment",
        "receiptTax",
        "receiptTotal",
        "closeReceipt",
        "checkDocumentClosed",
        "continuePrint",
        "get_shift_status",
        "openShift",
        "close_shift",
        "report",
    ):
        if code is not None and code != 0:
            return LAYER_KKT

    if code is None or code == 0:
        return LAYER_UNKNOWN
    return LAYER_UNKNOWN


def next_action_for_layer(layer: str) -> str:
    """Short 'What to do next' sentence (F-DIAG-04)."""
    return _NEXT_ACTIONS.get(layer, _NEXT_ACTIONS[LAYER_UNKNOWN])


def build_failure_record(
    *,
    layer: Optional[str] = None,
    step: Optional[str] = None,
    error_code: Any = None,
    error_description: Optional[str] = None,
    check_id: Any = None,
    message: Optional[str] = None,
    context: Optional[str] = None,
    override_layer: Optional[str] = None,
) -> dict[str, Any]:
    """Structured failure payload (F-DIAG-01)."""
    resolved_layer = layer or map_error_to_layer(
        error_code, step=step, context=context, override=override_layer
    )
    record = {
        "layer": resolved_layer,
        "step": step,
        "error_code": error_code,
        "error_description": error_description or message,
        "check_id": check_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "where": resolved_layer,
        "what_to_do_next": next_action_for_layer(resolved_layer),
    }
    if message:
        record["message"] = message
    return record


def remember_failure(record: dict[str, Any]) -> dict[str, Any]:
    """Store last process-level failure for /health and diagnostics."""
    global _last_failure
    _last_failure = dict(record)
    return _last_failure


def get_last_failure() -> Optional[dict[str, Any]]:
    return _last_failure
