"""Phase A fiscal sequence: cancel on mid-receipt failure; happy path order."""

from __future__ import annotations

import libfptr10


def _assert_never_success(result):
    assert result.get("code") != 201
    assert result.get("code") != 200


def test_fail_at_registration_cancels_receipt(service, flask_logger, sample_check):
    fptr = service.fptr
    fptr.fail_next("registration", code=42, desc="registration boom")

    result = service.print_check(sample_check, flask_logger)

    _assert_never_success(result)
    assert result["code"] == 500
    assert result["step"] == "registration"
    assert "cancelReceipt" in fptr.calls
    assert fptr.calls.index("openReceipt") < fptr.calls.index("registration")
    assert fptr.calls.index("registration") < fptr.calls.index("cancelReceipt")
    assert "payment" not in fptr.calls
    assert "closeReceipt" not in fptr.calls


def test_fail_at_payment_cancels_receipt(service, flask_logger, sample_check):
    fptr = service.fptr
    fptr.fail_next("payment", code=43, desc="payment boom")

    result = service.print_check(sample_check, flask_logger)

    _assert_never_success(result)
    assert result["code"] == 500
    assert result["step"] == "payment"
    assert "cancelReceipt" in fptr.calls
    assert "registration" in fptr.calls
    assert fptr.calls.index("payment") < fptr.calls.index("cancelReceipt")
    assert "closeReceipt" not in fptr.calls


def test_fail_at_receipt_tax_cancels_receipt(service, flask_logger, sample_check):
    fptr = service.fptr
    fptr.fail_next("receiptTax", code=128, desc="invalid tax sum")

    result = service.print_check(sample_check, flask_logger)

    _assert_never_success(result)
    assert result["code"] == 500
    assert result["error_code"] == 128
    assert result["step"] == "receiptTax"
    assert "cancelReceipt" in fptr.calls
    assert fptr.calls.index("openReceipt") < fptr.calls.index("receiptTax")
    assert fptr.calls.index("receiptTax") < fptr.calls.index("cancelReceipt")
    assert "receiptTotal" not in fptr.calls
    assert "closeReceipt" not in fptr.calls


def test_fail_at_close_cancels_or_recovers(service, flask_logger, sample_check):
    """
    closeReceipt failure → checkDocumentClosed; if still open → cancelReceipt.
    Never returns success (201).
    """
    fptr = service.fptr
    fptr.fail_next("closeReceipt", code=44, desc="close boom")
    fptr.document_closed = False
    fptr.document_printed = False

    result = service.print_check(sample_check, flask_logger)

    _assert_never_success(result)
    assert "closeReceipt" in fptr.calls
    assert "checkDocumentClosed" in fptr.calls
    assert "cancelReceipt" in fptr.calls
    assert result["code"] in (500, 504)


def test_happy_path_sequence_and_201(service, flask_logger, sample_check):
    fptr = service.fptr
    fptr.document_closed = True
    fptr.document_printed = True

    result = service.print_check(sample_check, flask_logger)

    assert result == {"code": 201}
    # open → register → pay → tax → total → close (cancel must not appear)
    expected = [
        "openReceipt",
        "registration",
        "payment",
        "receiptTax",
        "receiptTotal",
        "closeReceipt",
    ]
    # Filter to fiscal steps only (ignore checkDocumentClosed / beep)
    fiscal = [c for c in fptr.calls if c in expected or c == "cancelReceipt"]
    assert "cancelReceipt" not in fiscal
    assert fiscal[:6] == expected
    assert fptr.receipt_tax_params == [
        {
            libfptr10.IFptr.LIBFPTR_PARAM_TAX_TYPE: libfptr10.IFptr.LIBFPTR_TAX_NO,
            libfptr10.IFptr.LIBFPTR_PARAM_TAX_SUM: float(sample_check["sum"]),
        }
    ]
    assert isinstance(
        fptr.receipt_tax_params[0][libfptr10.IFptr.LIBFPTR_PARAM_TAX_SUM],
        float,
    )


def test_fake_receipt_tax_rejects_missing_tax_sum(fake_fptr_cls):
    fptr = fake_fptr_cls()
    fptr.setParam(
        libfptr10.IFptr.LIBFPTR_PARAM_TAX_TYPE,
        libfptr10.IFptr.LIBFPTR_TAX_NO,
    )

    result = fptr.receiptTax()

    assert result == -1
    assert fptr.errorCode() == 8
    assert fptr.receipt_tax_params == [
        {
            libfptr10.IFptr.LIBFPTR_PARAM_TAX_TYPE: libfptr10.IFptr.LIBFPTR_TAX_NO,
        }
    ]


def test_fake_receipt_tax_rejects_integer_tax_sum(fake_fptr_cls):
    fptr = fake_fptr_cls()
    fptr.setParam(
        libfptr10.IFptr.LIBFPTR_PARAM_TAX_TYPE,
        libfptr10.IFptr.LIBFPTR_TAX_NO,
    )
    fptr.setParam(libfptr10.IFptr.LIBFPTR_PARAM_TAX_SUM, 0)

    result = fptr.receiptTax()

    assert result == -1
    assert fptr.errorCode() == 8
    assert "must be passed as float" in fptr.errorDescription()


def test_fake_receipt_tax_rejects_zero_sum_for_tax_no(fake_fptr_cls):
    fptr = fake_fptr_cls()
    fptr.setParam(
        libfptr10.IFptr.LIBFPTR_PARAM_TAX_TYPE,
        libfptr10.IFptr.LIBFPTR_TAX_NO,
    )
    fptr.setParam(libfptr10.IFptr.LIBFPTR_PARAM_TAX_SUM, 0.0)

    result = fptr.receiptTax()

    assert result == -1
    assert fptr.errorCode() == libfptr10.IFptr.LIBFPTR_ERROR_INVALID_TAX_SUM
    assert "invalid tax sum" in fptr.errorDescription()


def test_payment_type_zero_maps_to_cash(service, flask_logger, sample_check):
    sample_check = dict(sample_check)
    sample_check["type"] = "0"
    fptr = service.fptr
    fptr.document_closed = True
    fptr.document_printed = True

    result = service.print_check(sample_check, flask_logger)
    assert result == {"code": 201}

    cash_calls = [
        args
        for args in fptr.set_param_calls
        if len(args) >= 2
        and args[0] == libfptr10.IFptr.LIBFPTR_PARAM_PAYMENT_TYPE
        and args[1] == libfptr10.IFptr.LIBFPTR_PT_CASH
    ]
    assert cash_calls, "expected LIBFPTR_PT_CASH for type '0'"
