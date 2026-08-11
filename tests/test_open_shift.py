"""Shift open timeout → 504 + retryable (F-FISC-05)."""

from __future__ import annotations

import libfptr10


def test_open_shift_timeout_returns_504_retryable(service, monkeypatch):
    fptr = service.fptr
    # Stay CLOSED so openShift polls until timeout
    fptr.shift_state = libfptr10.IFptr.LIBFPTR_SS_CLOSED

    # Avoid real 2s sleeps in the poll loop
    monkeypatch.setattr("cashierService.time.sleep", lambda *_: None)

    result = service.openShift(timeout_sec=0.05)

    assert result["code"] == 504
    assert result.get("retryable") is True
    assert "timed out" in result["message"].lower()
