"""
Runtime configuration (F-CFG-01–04).

Defaults ship in-code; optional overlay at ``instance/config.json`` (atomic write).
Missing file → defaults; app still starts. No secrets.
"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

# Project paths
_ROOT = Path(__file__).resolve().parent
INSTANCE_DIR = _ROOT / "instance"
CONFIG_PATH = INSTANCE_DIR / "config.json"

# F-CFG-02 + Phase A/B knobs kept as defaults (merge file over these)
DEFAULTS: dict[str, Any] = {
    "connection_mode": "usb",  # usb | tcp
    "kkt_ip": "",
    "kkt_tcp_port": 5555,
    "library_path": "/usr/lib/",
    # FSD §5.4 / Phase C: HTTP listen default 0.0.0.0:5000
    "http_host": "0.0.0.0",
    "http_port": 5000,
    "qr_wait_timeout_sec": 180,
    "shift_open_timeout_sec": 120,
    "shift_close_timeout_sec": 120,
    "document_close_timeout_sec": 60,
    "log_path": "atol.log",
    "max_log_lines": 300,
    # Phase B retention / reconnect / logging (not all exposed in Settings GUI)
    "check_retention_days": 30,
    "reconnect_max_attempts": 5,
    "reconnect_base_delay_sec": 1.0,
    "reconnect_max_delay_sec": 30.0,
    "log_max_bytes": 5_000_000,
    "log_backup_count": 10,
}

_PERSIST_KEYS = frozenset(DEFAULTS.keys())

_config: dict[str, Any] = {}


def _merge_defaults(overlay: Optional[dict] = None) -> dict[str, Any]:
    merged = deepcopy(DEFAULTS)
    if not overlay:
        return merged
    for key, value in overlay.items():
        if key in _PERSIST_KEYS:
            merged[key] = value
    return merged


def _sync_module_attrs(cfg: dict[str, Any]) -> None:
    """Keep legacy module-level names in sync for ``from conf import X`` / ``conf.X``."""
    global LIBRARY_PATH
    global SHIFT_OPEN_TIMEOUT_SEC, SHIFT_CLOSE_TIMEOUT_SEC
    global QR_WAIT_TIMEOUT_SEC, DOCUMENT_CLOSE_TIMEOUT_SEC
    global CHECK_RETENTION_DAYS
    global RECONNECT_MAX_ATTEMPTS, RECONNECT_BASE_DELAY_SEC, RECONNECT_MAX_DELAY_SEC
    global LOG_MAX_BYTES, LOG_BACKUP_COUNT
    global CONNECTION_MODE, KKT_IP, KKT_TCP_PORT
    global HTTP_HOST, HTTP_PORT, LOG_PATH, MAX_LOG_LINES

    LIBRARY_PATH = cfg["library_path"]
    SHIFT_OPEN_TIMEOUT_SEC = int(cfg["shift_open_timeout_sec"])
    SHIFT_CLOSE_TIMEOUT_SEC = int(cfg["shift_close_timeout_sec"])
    QR_WAIT_TIMEOUT_SEC = int(cfg["qr_wait_timeout_sec"])
    DOCUMENT_CLOSE_TIMEOUT_SEC = int(cfg["document_close_timeout_sec"])
    CHECK_RETENTION_DAYS = int(cfg["check_retention_days"])
    RECONNECT_MAX_ATTEMPTS = int(cfg["reconnect_max_attempts"])
    RECONNECT_BASE_DELAY_SEC = float(cfg["reconnect_base_delay_sec"])
    RECONNECT_MAX_DELAY_SEC = float(cfg["reconnect_max_delay_sec"])
    LOG_MAX_BYTES = int(cfg["log_max_bytes"])
    LOG_BACKUP_COUNT = int(cfg["log_backup_count"])
    CONNECTION_MODE = str(cfg["connection_mode"]).lower()
    KKT_IP = str(cfg.get("kkt_ip") or "")
    KKT_TCP_PORT = int(cfg["kkt_tcp_port"])
    HTTP_HOST = str(cfg["http_host"])
    HTTP_PORT = int(cfg["http_port"])
    LOG_PATH = str(cfg["log_path"])
    MAX_LOG_LINES = int(cfg["max_log_lines"])


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    """
    Load ``instance/config.json`` over defaults.
    Missing or invalid file → defaults (app still starts).
    """
    global _config
    cfg_path = Path(path) if path is not None else CONFIG_PATH
    overlay = None
    if cfg_path.is_file():
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                overlay = raw
        except (OSError, json.JSONDecodeError, TypeError):
            overlay = None
    _config = _merge_defaults(overlay)
    _sync_module_attrs(_config)
    return deepcopy(_config)


def get_config() -> dict[str, Any]:
    """Return a copy of the in-memory config (load once at import if empty)."""
    if not _config:
        load_config()
    return deepcopy(_config)


def save_config(
    updates: Optional[dict[str, Any]] = None,
    *,
    path: Optional[Path] = None,
    replace: bool = False,
) -> dict[str, Any]:
    """
    Merge ``updates`` into current config (or replace with defaults+updates if
    ``replace``), write atomically to ``instance/config.json``, refresh memory.
    """
    global _config
    cfg_path = Path(path) if path is not None else CONFIG_PATH
    base = deepcopy(DEFAULTS) if replace else get_config()
    if updates:
        for key, value in updates.items():
            if key in _PERSIST_KEYS:
                base[key] = value
    base = _merge_defaults(base)

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(base, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(cfg_path.parent),
        prefix=".config-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, cfg_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    _config = base
    _sync_module_attrs(_config)
    return deepcopy(_config)


def reset_config(*, path: Optional[Path] = None) -> dict[str, Any]:
    """Reset to shipped defaults and persist."""
    return save_config(None, path=path, replace=True)


def validate_settings_payload(data: dict[str, Any]) -> list[str]:
    """Validate Settings form/JSON; return list of error strings (empty = OK)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Body must be a JSON object"]

    mode = data.get("connection_mode")
    if mode is not None:
        mode_l = str(mode).lower()
        if mode_l not in ("usb", "tcp"):
            errors.append("connection_mode must be 'usb' or 'tcp'")
    else:
        mode_l = get_config().get("connection_mode", "usb")

    if "kkt_tcp_port" in data and data["kkt_tcp_port"] is not None:
        try:
            port = int(data["kkt_tcp_port"])
            if not (1 <= port <= 65535):
                errors.append("kkt_tcp_port must be 1–65535")
        except (TypeError, ValueError):
            errors.append("kkt_tcp_port must be an integer")

    if "http_port" in data and data["http_port"] is not None:
        try:
            hport = int(data["http_port"])
            if not (1 <= hport <= 65535):
                errors.append("http_port must be 1–65535")
        except (TypeError, ValueError):
            errors.append("http_port must be an integer")

    for key in (
        "qr_wait_timeout_sec",
        "shift_open_timeout_sec",
        "shift_close_timeout_sec",
        "document_close_timeout_sec",
        "max_log_lines",
    ):
        if key in data and data[key] is not None and data[key] != "":
            try:
                val = int(data[key])
                if val < 1:
                    errors.append(f"{key} must be >= 1")
            except (TypeError, ValueError):
                errors.append(f"{key} must be an integer")

    effective_mode = mode_l
    if effective_mode == "tcp":
        ip = data.get("kkt_ip")
        if ip is None:
            ip = get_config().get("kkt_ip", "")
        if not str(ip).strip():
            errors.append(
                "kkt_ip is required for TCP mode "
                "(Driver TCP target: Orange Pi → KKT)"
            )

    if "library_path" in data and data["library_path"] is not None:
        if not str(data["library_path"]).strip():
            errors.append("library_path must not be empty")

    return errors


def coerce_settings_updates(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize validated Settings fields for save_config."""
    out: dict[str, Any] = {}
    if "connection_mode" in data and data["connection_mode"] is not None:
        out["connection_mode"] = str(data["connection_mode"]).lower()
    if "kkt_ip" in data and data["kkt_ip"] is not None:
        out["kkt_ip"] = str(data["kkt_ip"]).strip()
    if "kkt_tcp_port" in data and data["kkt_tcp_port"] not in (None, ""):
        out["kkt_tcp_port"] = int(data["kkt_tcp_port"])
    if "library_path" in data and data["library_path"] is not None:
        out["library_path"] = str(data["library_path"]).strip()
    if "http_host" in data and data["http_host"] is not None:
        out["http_host"] = str(data["http_host"]).strip() or "0.0.0.0"
    if "http_port" in data and data["http_port"] not in (None, ""):
        out["http_port"] = int(data["http_port"])
    if "qr_wait_timeout_sec" in data and data["qr_wait_timeout_sec"] not in (None, ""):
        out["qr_wait_timeout_sec"] = int(data["qr_wait_timeout_sec"])
    if "shift_open_timeout_sec" in data and data["shift_open_timeout_sec"] not in (
        None,
        "",
    ):
        out["shift_open_timeout_sec"] = int(data["shift_open_timeout_sec"])
    if "log_path" in data and data["log_path"] is not None:
        out["log_path"] = str(data["log_path"]).strip() or "atol.log"
    if "max_log_lines" in data and data["max_log_lines"] not in (None, ""):
        out["max_log_lines"] = int(data["max_log_lines"])
    return out


# Load on import so CashierService / main see merged values immediately
load_config()

# Module-level aliases (populated by load_config → _sync_module_attrs)
LIBRARY_PATH: str
SHIFT_OPEN_TIMEOUT_SEC: int
SHIFT_CLOSE_TIMEOUT_SEC: int
QR_WAIT_TIMEOUT_SEC: int
DOCUMENT_CLOSE_TIMEOUT_SEC: int
CHECK_RETENTION_DAYS: int
RECONNECT_MAX_ATTEMPTS: int
RECONNECT_BASE_DELAY_SEC: float
RECONNECT_MAX_DELAY_SEC: float
LOG_MAX_BYTES: int
LOG_BACKUP_COUNT: int
CONNECTION_MODE: str
KKT_IP: str
KKT_TCP_PORT: int
HTTP_HOST: str
HTTP_PORT: int
LOG_PATH: str
MAX_LOG_LINES: int
