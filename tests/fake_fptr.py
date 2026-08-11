"""Hardware-free stand-in for libfptr10.IFptr (constants + controllable methods)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple


def build_fake_fptr_class(real_cls: type) -> type:
    """Copy LIBFPTR_* class attrs from the real IFptr; never load the native .so/.dylib."""

    class FakeIFptr:
        def __init__(self, lib_path: str = "", fptr_id: str = ""):
            self.lib_path = lib_path
            self._error_code = 0
            self._error_desc = ""
            self._opened = 1
            self._params: Dict[Any, Any] = {}
            self.calls: List[str] = []
            self.set_param_calls: List[Tuple[Any, ...]] = []
            # Methods that should fail on next call (nonzero return + errorCode)
            self._fail_once: Set[str] = set()
            self._fail_always: Set[str] = set()
            self._error_on_fail = 1
            self._desc_on_fail = "simulated native error"
            # Shift state for get_shift_status / openShift polling
            self.shift_state = real_cls.LIBFPTR_SS_OPENED
            # Document closure flags for checkDocumentClosed path
            self.document_closed = True
            self.document_printed = True
            # Optional hook: called each get_shift_status query (for timeout tests)
            self.on_shift_query: Optional[Callable[[], None]] = None

        def _record(self, name: str) -> int:
            self.calls.append(name)
            if name in self._fail_once:
                self._fail_once.discard(name)
                self._error_code = self._error_on_fail
                self._error_desc = self._desc_on_fail
                return -1
            if name in self._fail_always:
                self._error_code = self._error_on_fail
                self._error_desc = self._desc_on_fail
                return -1
            self._error_code = 0
            self._error_desc = ""
            return 0

        def fail_next(self, *methods: str, code: int = 1, desc: str = "simulated native error"):
            self._fail_once.update(methods)
            self._error_on_fail = code
            self._desc_on_fail = desc

        def fail_always(self, *methods: str, code: int = 1, desc: str = "simulated native error"):
            self._fail_always.update(methods)
            self._error_on_fail = code
            self._desc_on_fail = desc

        # --- settings / connection ---
        def setSingleSetting(self, key, value=None):
            self.calls.append("setSingleSetting")
            if not hasattr(self, "_settings"):
                self._settings = {}
            self._settings[key] = value
            return None

        def applySingleSettings(self):
            return self._record("applySingleSettings")

        def open(self):
            result = self._record("open")
            if result == 0:
                self._opened = 1
            else:
                self._opened = 0
            return result

        def close(self):
            self.calls.append("close")
            self._opened = 0
            self._error_code = 0
            self._error_desc = ""
            return 0

        def isOpened(self):
            return self._opened

        def enableOfdChannel(self):
            return self._record("enableOfdChannel")

        def errorCode(self):
            return self._error_code

        def errorDescription(self):
            return self._error_desc

        def setParam(self, *args):
            self.set_param_calls.append(args)
            if len(args) >= 2:
                self._params[args[0]] = args[1]
            return None

        def getParamInt(self, key):
            if key == real_cls.LIBFPTR_PARAM_SHIFT_STATE:
                if self.on_shift_query is not None:
                    self.on_shift_query()
                return int(self.shift_state)
            return int(self._params.get(key, 0) or 0)

        def getParamBool(self, key):
            if key == real_cls.LIBFPTR_PARAM_DOCUMENT_CLOSED:
                return bool(self.document_closed)
            if key == real_cls.LIBFPTR_PARAM_DOCUMENT_PRINTED:
                return bool(self.document_printed)
            return bool(self._params.get(key, False))

        def getParamString(self, key):
            return str(self._params.get(key, ""))

        def queryData(self):
            return self._record("queryData")

        # --- receipt sequence ---
        def openReceipt(self):
            return self._record("openReceipt")

        def registration(self):
            return self._record("registration")

        def payment(self):
            return self._record("payment")

        def receiptTax(self):
            return self._record("receiptTax")

        def receiptTotal(self):
            return self._record("receiptTotal")

        def closeReceipt(self):
            return self._record("closeReceipt")

        def cancelReceipt(self):
            return self._record("cancelReceipt")

        def checkDocumentClosed(self):
            return self._record("checkDocumentClosed")

        def continuePrint(self):
            return self._record("continuePrint")

        def beep(self):
            return self._record("beep")

        def openShift(self):
            return self._record("openShift")

        def report(self):
            return self._record("report")

        def fnQueryData(self):
            return self._record("fnQueryData")

        def processJson(self):
            return self._record("processJson")

    for name in dir(real_cls):
        if name.startswith("LIBFPTR_"):
            setattr(FakeIFptr, name, getattr(real_cls, name))

    return FakeIFptr
