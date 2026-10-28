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
_ROOT = Path(__file__).resolve().parents[2]
INSTANCE_DIR = _ROOT / "instance"
CONFIG_PATH = INSTANCE_DIR / "config.json"

TAX_TYPE_LABELS: dict[str, str] = {
    "no_vat": "Без НДС",
    "vat0": "НДС 0%",
    "vat5": "НДС 5%",
    "vat7": "НДС 7%",
    "vat10": "НДС 10%",
    "vat22": "НДС 22%",
}

# F-CFG-02 + Phase A/B knobs kept as defaults (merge file over these)
DEFAULTS: dict[str, Any] = {
    "connection_mode": "usb",  # usb | tcp
    "kkt_ip": "",
    "kkt_tcp_port": 5555,
    "library_path": "/usr/lib/",
    # Empty preserves the KKT's existing/default operator until configured.
    "cashier_name": "",
    "cashier_inn": "",
    # Explicitly controls tags 1021/1203 + operatorLogin(). Disabling this
    # does not clear an operator already stored inside the KKT.
    "send_cashier_to_kkt": True,
    # Application guard for KKT registered as part of automatic devices.
    # Tag 1001 comes from KKT registration; the app supplies tag 1036.
    "automatic_mode": False,
    # One registered automatic-device number for all internal bays. When set,
    # this takes precedence over the legacy per-bay mapping below.
    "machine_number": "",
    "machine_numbers_by_bay": {},
    "qr_displays": {
        "wash": {"count": 0, "screens": {}},
        "robot": {"count": 0, "screens": {}},
        "vacuum": {"count": 0, "screens": {}},
    },
    "tax_type": "no_vat",
    # HTTP listen default 0.0.0.0:5000
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
    "monitoring_url": "",
    "monitoring_pos_id": None,
    "monitoring_api_key": "",
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
    global CASHIER_NAME, CASHIER_INN, SEND_CASHIER_TO_KKT, TAX_TYPE
    global AUTOMATIC_MODE, MACHINE_NUMBER, MACHINE_NUMBERS_BY_BAY

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
    CASHIER_NAME = str(cfg.get("cashier_name") or "")
    CASHIER_INN = str(cfg.get("cashier_inn") or "")
    SEND_CASHIER_TO_KKT = normalize_send_cashier_to_kkt(
        cfg.get("send_cashier_to_kkt", True)
    )[0]
    AUTOMATIC_MODE = normalize_automatic_mode(
        cfg.get("automatic_mode", False)
    )[0]
    MACHINE_NUMBER = normalize_machine_number(cfg.get("machine_number", ""))[0]
    MACHINE_NUMBERS_BY_BAY = normalize_machine_numbers_by_bay(
        cfg.get("machine_numbers_by_bay", {})
    )[0]
    TAX_TYPE = str(cfg.get("tax_type") or "")
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
    migrate_http_port = False
    if cfg_path.is_file():
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                overlay = dict(raw)
                # Migrate old installations to the default HTTP port.
                if overlay.get("http_port") in (5050, "5050", 5051, "5051"):
                    overlay["http_port"] = DEFAULTS["http_port"]
                    migrate_http_port = True
        except (OSError, json.JSONDecodeError, TypeError):
            overlay = None
    _config = _merge_defaults(overlay)
    _sync_module_attrs(_config)
    if migrate_http_port:
        save_config(path=cfg_path)
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


def normalize_cashier_identity(
    cashier_name: Any, cashier_inn: Any
) -> tuple[str, str, list[str]]:
    """Normalize and validate fiscal tags 1021/1203."""
    name = str(cashier_name or "").strip()
    inn = str(cashier_inn or "").strip()
    errors: list[str] = []
    if len(name) > 64:
        errors.append("cashier_name must be at most 64 characters")
    if any(not char.isprintable() for char in name):
        errors.append("cashier_name must not contain control characters")
    if inn and (len(inn) != 12 or not inn.isascii() or not inn.isdigit()):
        errors.append("cashier_inn must contain exactly 12 digits")
    if inn and not name:
        errors.append("cashier_name is required when cashier_inn is set")
    return name, inn, errors


def normalize_send_cashier_to_kkt(value: Any) -> tuple[bool, list[str]]:
    """Normalize the explicit operatorLogin/tags 1021/1203 switch."""
    if isinstance(value, bool):
        return value, []
    if isinstance(value, int) and value in (0, 1):
        return bool(value), []

    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True, []
    if normalized in ("0", "false", "no", "off"):
        return False, []
    return True, ["send_cashier_to_kkt must be true or false"]


def normalize_automatic_mode(value: Any) -> tuple[bool, list[str]]:
    """Normalize the application guard for automatic-device receipts."""
    if isinstance(value, bool):
        return value, []
    if isinstance(value, int) and value in (0, 1):
        return bool(value), []

    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True, []
    if normalized in ("0", "false", "no", "off"):
        return False, []
    return False, ["automatic_mode must be true or false"]


def normalize_machine_numbers_by_bay(
    value: Any,
) -> tuple[dict[str, str], list[str]]:
    """Parse ``bay=machine number`` rows or a JSON object for fiscal tag 1036."""
    errors: list[str] = []
    rows: list[tuple[Any, Any, Optional[int]]] = []

    if value is None or value == "":
        return {}, []
    if isinstance(value, dict):
        rows = [(key, number, None) for key, number in value.items()]
    elif isinstance(value, str):
        for line_number, raw_line in enumerate(value.splitlines(), start=1):
            if not raw_line.strip():
                continue
            if "=" not in raw_line:
                errors.append(
                    f"machine_numbers_by_bay line {line_number} must use bay=number"
                )
                continue
            bay, number = raw_line.split("=", 1)
            rows.append((bay, number, line_number))
    else:
        return {}, ["machine_numbers_by_bay must be an object or bay=number lines"]

    normalized: dict[str, str] = {}
    number_owners: dict[str, str] = {}
    for raw_bay, raw_number, line_number in rows:
        bay = "" if raw_bay is None else str(raw_bay).strip()
        number = "" if raw_number is None else str(raw_number).strip()
        where = f" on line {line_number}" if line_number is not None else ""

        if not bay:
            errors.append(f"post ID must not be empty{where}")
            continue
        if len(bay) > 50:
            errors.append(f"post ID must be at most 50 characters{where}")
        if any(not char.isprintable() for char in bay):
            errors.append(f"post ID must not contain control characters{where}")
        if not number:
            errors.append(f"machine number must not be empty{where}")
            continue
        if len(number) > 20:
            errors.append(f"machine number must be at most 20 characters{where}")
        if any(not char.isprintable() for char in number):
            errors.append(f"machine number must not contain control characters{where}")
        if bay in normalized:
            errors.append(f"duplicate post ID {bay!r}{where}")
            continue
        owner = number_owners.get(number)
        if owner is not None and owner != bay:
            errors.append(
                f"machine number {number!r} is already assigned to post {owner!r}"
            )
            continue
        normalized[bay] = number
        number_owners[number] = bay

    return normalized, errors


def normalize_machine_number(value: Any) -> tuple[str, list[str]]:
    """Normalize one registered automatic-device number for fiscal tag 1036."""
    number = str(value or "").strip()
    errors: list[str] = []
    if len(number) > 20:
        errors.append("machine_number must be at most 20 characters")
    if any(not char.isprintable() for char in number):
        errors.append("machine_number must not contain control characters")
    return number, errors


def resolve_machine_number(
    cfg: dict[str, Any], bay: Any
) -> tuple[Optional[str], list[str]]:
    """Resolve tag 1036 for a receipt, failing closed in automatic mode."""
    automatic_mode, mode_errors = normalize_automatic_mode(
        cfg.get("automatic_mode", False)
    )
    if mode_errors:
        return None, mode_errors
    if not automatic_mode:
        return None, []

    machine_number, machine_number_errors = normalize_machine_number(
        cfg.get("machine_number", "")
    )
    if machine_number_errors:
        return None, machine_number_errors
    if machine_number:
        return machine_number, []

    numbers, mapping_errors = normalize_machine_numbers_by_bay(
        cfg.get("machine_numbers_by_bay", {})
    )
    errors = list(mapping_errors)
    if not numbers:
        errors.append(
            "machine_number or machine_numbers_by_bay is required in automatic mode"
        )
        return None, errors

    post_id = "" if bay is None else str(bay).strip()
    if not post_id:
        errors.append("bay is required in automatic mode")
        return None, errors
    machine_number = numbers.get(post_id)
    if machine_number is None:
        errors.append(f"no machine number configured for bay {post_id!r}")
        return None, errors
    return machine_number, errors


def normalize_tax_type(tax_type: Any) -> tuple[str, list[str]]:
    """Normalize and validate the configured fiscal tax-rate key."""
    normalized = str(tax_type or "").strip().lower()
    if normalized not in TAX_TYPE_LABELS:
        allowed = ", ".join(TAX_TYPE_LABELS)
        return normalized, [f"tax_type must be one of: {allowed}"]
    return normalized, []


def normalize_monitoring_url(value: Any) -> tuple[str, list[str]]:
    if value is None:
        return "", []
    text = str(value).strip().rstrip("/")
    if not text:
        return "", []
    if text.endswith("/data/fiscal"):
        text = text[: -len("/data/fiscal")].rstrip("/")
    if not (text.startswith("http://") or text.startswith("https://")):
        return "", ["monitoring_url must start with http:// or https://"]
    return text, []


def normalize_monitoring_pos_id(value: Any) -> tuple[Optional[int], list[str]]:
    if value is None or value == "":
        return None, []
    if isinstance(value, bool):
        return None, ["monitoring_pos_id must be a positive integer"]
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None, ["monitoring_pos_id must be a positive integer"]
    if number <= 0:
        return None, ["monitoring_pos_id must be a positive integer"]
    return number, []


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

    current = get_config()
    _, _, cashier_errors = normalize_cashier_identity(
        data.get("cashier_name", current.get("cashier_name", "")),
        data.get("cashier_inn", current.get("cashier_inn", "")),
    )
    errors.extend(cashier_errors)

    _, send_cashier_errors = normalize_send_cashier_to_kkt(
        data.get(
            "send_cashier_to_kkt",
            current.get("send_cashier_to_kkt", True),
        )
    )
    errors.extend(send_cashier_errors)

    automatic_mode, automatic_mode_errors = normalize_automatic_mode(
        data.get("automatic_mode", current.get("automatic_mode", False))
    )
    errors.extend(automatic_mode_errors)
    machine_number, global_machine_number_errors = normalize_machine_number(
        data.get("machine_number", current.get("machine_number", ""))
    )
    errors.extend(global_machine_number_errors)
    machine_numbers, machine_number_errors = normalize_machine_numbers_by_bay(
        data.get(
            "machine_numbers_by_bay",
            current.get("machine_numbers_by_bay", {}),
        )
    )
    errors.extend(machine_number_errors)
    if automatic_mode and not machine_number and not machine_numbers:
        errors.append(
            "machine_number or machine_numbers_by_bay is required in automatic mode"
        )

    _, tax_errors = normalize_tax_type(
        data.get("tax_type", current.get("tax_type"))
    )
    errors.extend(tax_errors)

    if "monitoring_url" in data:
        _, url_errors = normalize_monitoring_url(data.get("monitoring_url"))
        errors.extend(url_errors)
    if "monitoring_pos_id" in data:
        _, pos_errors = normalize_monitoring_pos_id(data.get("monitoring_pos_id"))
        errors.extend(pos_errors)

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
    if "cashier_name" in data and data["cashier_name"] is not None:
        out["cashier_name"] = str(data["cashier_name"]).strip()
    if "cashier_inn" in data and data["cashier_inn"] is not None:
        out["cashier_inn"] = str(data["cashier_inn"]).strip()
    if (
        "send_cashier_to_kkt" in data
        and data["send_cashier_to_kkt"] is not None
    ):
        out["send_cashier_to_kkt"] = normalize_send_cashier_to_kkt(
            data["send_cashier_to_kkt"]
        )[0]
    if "automatic_mode" in data and data["automatic_mode"] is not None:
        out["automatic_mode"] = normalize_automatic_mode(
            data["automatic_mode"]
        )[0]
    if "machine_number" in data and data["machine_number"] is not None:
        out["machine_number"] = normalize_machine_number(
            data["machine_number"]
        )[0]
    if (
        "machine_numbers_by_bay" in data
        and data["machine_numbers_by_bay"] is not None
    ):
        out["machine_numbers_by_bay"] = normalize_machine_numbers_by_bay(
            data["machine_numbers_by_bay"]
        )[0]
    if "tax_type" in data and data["tax_type"] is not None:
        out["tax_type"] = str(data["tax_type"]).strip().lower()
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
    if "monitoring_url" in data and data["monitoring_url"] is not None:
        out["monitoring_url"] = normalize_monitoring_url(data["monitoring_url"])[0]
    if "monitoring_pos_id" in data:
        out["monitoring_pos_id"] = normalize_monitoring_pos_id(
            data.get("monitoring_pos_id")
        )[0]
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
CASHIER_NAME: str
CASHIER_INN: str
SEND_CASHIER_TO_KKT: bool
AUTOMATIC_MODE: bool
MACHINE_NUMBER: str
MACHINE_NUMBERS_BY_BAY: dict[str, str]
TAX_TYPE: str
HTTP_HOST: str
HTTP_PORT: int
LOG_PATH: str
MAX_LOG_LINES: int
