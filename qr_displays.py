"""Telemetron screen configuration and bounded raw TCP transport (no KKT access)."""
from __future__ import annotations

import ipaddress
import re
import socket
import time
from copy import deepcopy

GROUPS = (("wash", "Посты самообслуживания", "Пост"),
          ("robot", "Роботы", "Робот"), ("vacuum", "Пылесосы", "Пылесос"))
MAX_SCREENS = 100
DEFAULT_PORT = 5000


def normalized_config(raw):
    """Fail closed on an invalid persisted mapping rather than misroute a receipt."""
    result = {}
    for key, _, _ in GROUPS:
        group = raw.get(key, {}) if isinstance(raw, dict) else {}
        if not isinstance(group, dict):
            group = {}
        count = group.get("count", 0)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_SCREENS:
            count = 0
        screens = group.get("screens", {})
        result[key] = {"count": count, "screens": deepcopy(screens) if isinstance(screens, dict) else {}}
    return result


def save_counts(current, counts):
    result = normalized_config(current)
    errors = []
    if not isinstance(counts, dict):
        return result, ["Количество устройств должно быть объектом."]
    for key, label, _ in GROUPS:
        value = counts.get(key, result[key]["count"])
        if isinstance(value, bool) or len(str(value)) > 3 or not re.fullmatch(r"[0-9]+", str(value)):
            errors.append(f"{label}: введите целое число от 0 до {MAX_SCREENS}.")
            continue
        count = int(value)
        if not 0 <= count <= MAX_SCREENS:
            errors.append(f"{label}: допустимо от 0 до {MAX_SCREENS}.")
            continue
        result[key]["count"] = count
        # Preserve disabled addresses so an accidental count change is reversible.
    return result, errors


def _address(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("Введите IP-адрес без http:// и без номера порта.") from exc
    if ip.is_unspecified or ip.is_multicast or str(ip) == "255.255.255.255":
        raise ValueError("Нужен адрес одного устройства.")
    return str(ip)


def save_addresses(current, addresses):
    result = normalized_config(current)
    errors, owners = [], {}
    if not isinstance(addresses, dict):
        return result, ["Адреса экранов должны быть объектом."]
    for key, _, label in GROUPS:
        submitted = addresses.get(key, {})
        if not isinstance(submitted, dict):
            errors.append(f"{label}: неверный список экранов.")
            continue
        for number in range(1, result[key]["count"] + 1):
            bay = str(number)
            entry = submitted.get(bay, result[key]["screens"].get(bay, {}))
            if not isinstance(entry, dict):
                errors.append(f"{label} {bay}: неверный адрес экрана.")
                continue
            ip = str(entry.get("ip") or "").strip()
            port = entry.get("port", DEFAULT_PORT)
            try:
                if isinstance(port, bool) or len(str(port)) > 5 or not re.fullmatch(r"[0-9]+", str(port)):
                    raise ValueError("TCP-порт должен быть целым числом.")
                port = int(port)
                if not 1 <= port <= 65535:
                    raise ValueError("TCP-порт должен быть от 1 до 65535.")
                if ip:
                    ip = _address(ip)
                    endpoint = (ip, port)
                    if endpoint in owners:
                        raise ValueError(f"Этот экран уже назначен: {owners[endpoint]}.")
                    owners[endpoint] = f"{label} {bay}"
                result[key]["screens"][bay] = {"ip": ip, "port": port}
            except ValueError as exc:
                errors.append(f"{label} {bay}: {exc}")
    return result, errors


def endpoint(config, category, bay):
    group = normalized_config(config).get(category)
    if not group or len(str(bay)) > 3 or not re.fullmatch(r"[0-9]+", str(bay)):
        return None
    number = int(bay)
    if not 1 <= number <= group["count"]:
        return None
    entry = group["screens"].get(str(number), {})
    if not isinstance(entry, dict) or not entry.get("ip"):
        return None
    try:
        ip = _address(str(entry["ip"]))
        port = entry.get("port", DEFAULT_PORT)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return None
        return ip, port
    except ValueError:
        return None


def category_for_name(name):
    for key, _, label in GROUPS:
        if str(name).startswith(label + " "):
            return key
    return None


def qr_packet(data):
    if not isinstance(data, str) or not data.strip():
        raise ValueError("QR не должен быть пустым.")
    payload = data.encode("utf-8")
    if len(payload) > 200 or any(b < 32 or b == 127 or b >= 240 for b in payload):
        raise ValueError("QR: до 200 байт UTF-8, без управляющих символов и эмодзи.")
    return b"qr=" + payload + b"\n"


def _read(connection, seconds=3):
    deadline, last_byte = time.monotonic() + seconds, time.monotonic()
    reply = bytearray()
    while time.monotonic() < deadline:
        connection.settimeout(min(0.1, max(0.001, deadline - time.monotonic())))
        try:
            chunk = connection.recv(1024)
        except socket.timeout:
            if reply and time.monotonic() - last_byte >= 0.3:
                break
            continue
        if not chunk:
            break
        reply.extend(chunk)
        last_byte = time.monotonic()
        if len(reply) > 16384:
            raise OSError("Слишком большой ответ устройства.")
    return bytes(reply)


def communicate(ip, port, data=None):
    """info first; an echo confirms protocol receipt, not phone readability."""
    packet = qr_packet(data) if data is not None else None
    ip = _address(ip)
    try:
        connection = socket.create_connection((ip, port), timeout=1.5)
    except OSError as exc:
        raise OSError(f"Нет TCP-соединения с экраном {ip}:{port}. Проверьте питание, сеть и порт.") from exc
    with connection:
        connection.sendall(b"info\n")
        info = _read(connection)
        if b"http://telemetron.ru/" not in info or not re.search(rb"(?m)^hw=[^;\r\n]+;", info) or not re.search(rb"(?m)^swm=[^;\r\n]+;", info):
            raise OSError("Нет ответа Telemetron. Проверьте питание, UART 2400 8N1 и проводку.")
        if packet is not None:
            connection.settimeout(1.5)
            connection.sendall(packet)
            reply = _read(connection)
            expected = packet[:-1]
            lines = reply.replace(b"\r", b"").split(b"\n")
            if not any(line == expected or re.fullmatch(rb"rb[01]\[\d+\]=" + re.escape(expected), line) for line in lines):
                raise OSError("Команда отправлена, но экран не подтвердил её приём.")
    return info.decode("utf-8", errors="replace")
