import json
import logging
import threading
import time
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import enum

import conf
from libfptr10 import IFptr
from fault_isolation import (
	LAYER_LINK,
	LAYER_FN_OFD,
	build_failure_record,
	map_error_to_layer,
	next_action_for_layer,
	remember_failure,
)

_log = logging.getLogger(__name__)


class ShiftSatus(enum.Enum):
	OPEN = 1
	CLOSED = 0
	EXPIRED = 2


def _money(value):
	"""Decimal-safe money: avoid bare int() truncating kopecks on floats."""
	try:
		return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
	except (InvalidOperation, TypeError, ValueError) as exc:
		raise ValueError(f"Invalid money value: {value!r}") from exc


class CashierService:
	def __init__(self):
		self._lock = threading.RLock()
		self._library_path = None
		self._initialize_device()

	def _connection_mode(self):
		mode = str(conf.get_config().get("connection_mode") or "usb").lower()
		return "tcp" if mode == "tcp" else "usb"

	def _apply_port_settings(self):
		"""
		USB | TCP driver reachability only (F-CONN-01–03, F-CONN-06).
		No mass OFD/Wi‑Fi/device-table rewrite on boot — provisioning is separate.
		Call order: setSingleSetting* → applySingleSettings → open (elsewhere).
		"""
		cfg = conf.get_config()
		self.fptr.setSingleSetting(
			IFptr.LIBFPTR_SETTING_MODEL, str(IFptr.LIBFPTR_MODEL_ATOL_AUTO)
		)
		mode = self._connection_mode()
		if mode == "tcp":
			self.fptr.setSingleSetting(
				IFptr.LIBFPTR_SETTING_PORT, str(IFptr.LIBFPTR_PORT_TCPIP)
			)
			self.fptr.setSingleSetting(
				IFptr.LIBFPTR_SETTING_IPADDRESS, str(cfg.get("kkt_ip") or "")
			)
			self.fptr.setSingleSetting(
				IFptr.LIBFPTR_SETTING_IPPORT,
				str(int(cfg.get("kkt_tcp_port") or 5555)),
			)
		else:
			self.fptr.setSingleSetting(
				IFptr.LIBFPTR_SETTING_PORT, str(IFptr.LIBFPTR_PORT_USB)
			)
		self.fptr.setSingleSetting(
			IFptr.LIBFPTR_SETTING_OFD_CHANNEL, str(IFptr.LIBFPTR_OFD_CHANNEL_AUTO)
		)
		result = self.fptr.applySingleSettings()
		error_code = self.fptr.errorCode()
		if result != 0 or error_code != 0:
			return False, self._native_error(
				"applySingleSettings",
				context="connect",
				override_layer=LAYER_LINK,
			)
		return True, None

	def _initialize_device(self):
		"""Runtime connect settings only (F-CONN-06). OFD/network provisioning is separate."""
		library_path = conf.get_config().get("library_path") or conf.LIBRARY_PATH
		self._library_path = library_path
		self.fptr = IFptr(library_path)
		ok, err = self._apply_port_settings()
		if not ok:
			_log.error(
				"Initial applySingleSettings failed: %s",
				(err or {}).get("message"),
			)

	def is_busy(self):
		"""Cheap: True if another thread holds the device RLock (fiscal op in progress)."""
		acquired = self._lock.acquire(blocking=False)
		if acquired:
			self._lock.release()
			return False
		return True

	def connection_info(self):
		"""Admin Status: mode + TCP target (never exposes IFptr)."""
		cfg = conf.get_config()
		mode = self._connection_mode()
		return {
			"connection_mode": mode,
			"kkt_ip": cfg.get("kkt_ip") or "",
			"kkt_tcp_port": int(cfg.get("kkt_tcp_port") or 5555),
			"library_path": cfg.get("library_path") or conf.LIBRARY_PATH,
			"busy": self.is_busy(),
		}

	def apply_settings_and_reconnect(self, logger=None, *, max_attempts=None):
		"""
		Re-read conf, applySingleSettings, then open with F-CONN-04 backoff.
		Callable from Admin Settings (Save & reconnect) / Status Reconnect.
		"""
		log = logger or _log
		with self._lock:
			cfg = conf.get_config()
			new_path = cfg.get("library_path") or conf.LIBRARY_PATH
			try:
				if hasattr(self.fptr, "close"):
					try:
						if self.fptr.isOpened() != 0:
							self.fptr.close()
					except Exception as close_exc:
						log.debug("close before apply_settings: %s", close_exc)

				if self._library_path != new_path:
					self.fptr = IFptr(new_path)
					self._library_path = new_path

				ok, err = self._apply_port_settings()
				if not ok:
					return err or {
						"code": 500,
						"message": "applySingleSettings failed",
						"layer": LAYER_LINK,
						"where": LAYER_LINK,
						"opened": False,
					}
			except Exception as e:
				record = build_failure_record(
					step="apply_settings",
					message=str(e),
					error_description=str(e),
					context="connect",
					override_layer=LAYER_LINK,
				)
				remember_failure(record)
				log.error("apply_settings_and_reconnect raised: %s", e, exc_info=True)
				return {
					"code": 500,
					"message": "Failed to apply connection settings",
					"step": "apply_settings",
					"layer": LAYER_LINK,
					"where": LAYER_LINK,
					"what_to_do_next": record["what_to_do_next"],
					"opened": False,
				}

		return self.ensure_connected(logger=log, max_attempts=max_attempts)

	def _native_error(self, step, *, context=None, override_layer=None, check_id=None):
		error_code = self.fptr.errorCode()
		error_description = self.fptr.errorDescription()
		layer = map_error_to_layer(
			error_code, step=step, context=context, override=override_layer
		)
		record = build_failure_record(
			layer=layer,
			step=step,
			error_code=error_code,
			error_description=error_description,
			check_id=check_id,
			message=f"{step} failed: {error_description}",
		)
		remember_failure(record)
		return {
			"code": 500,
			"message": f"{step} failed: {error_description}",
			"error_code": error_code,
			"error_description": error_description,
			"step": step,
			"layer": layer,
			"where": layer,
			"what_to_do_next": record["what_to_do_next"],
			"check_id": check_id,
		}

	def _call_ok(self, result, step, *, context=None, override_layer=None, check_id=None):
		"""ATOL: nonzero return or nonzero errorCode() means failure."""
		error_code = self.fptr.errorCode()
		if result != 0 or error_code != 0:
			return False, self._native_error(
				step,
				context=context,
				override_layer=override_layer,
				check_id=check_id,
			)
		return True, None

	def _is_port_unavailable(self, error_code=None):
		"""Error-4 class / not opened (F-CONN-04)."""
		if error_code is None:
			error_code = self.fptr.errorCode()
		try:
			code = int(error_code)
		except (TypeError, ValueError):
			code = -1
		return code in (
			IFptr.LIBFPTR_ERROR_PORT_NOT_AVAILABLE,
			IFptr.LIBFPTR_ERROR_NO_CONNECTION,
			IFptr.LIBFPTR_ERROR_CONNECTION_DISABLED,
			IFptr.LIBFPTR_ERROR_PORT_BUSY,
			getattr(IFptr, "LIBFPTR_ERROR_CONNECTION_LOST", 241),
		)

	def ensure_connected(self, logger=None, *, reconnect=True, max_attempts=None):
		"""
		Ensure device is open; on isOpened==0 / error-4 class, reconnect with
		exponential backoff (F-CONN-04). USB or TCP per conf (F-CONN-01–03).

		reconnect=False: never open()/backoff — report not-opened immediately
		(for /health best-effort queries that must not starve job1).
		max_attempts: override reconnect_max_attempts (use 1 for diagnostics/boot).
		"""
		log = logger or _log
		with self._lock:
			try:
				# Already open — do not require errorCode==0 (prior call may leave stale code)
				if self.fptr.isOpened() != 0:
					return {"code": 200, "message": "Connection open", "opened": True}

				if not reconnect:
					return {
						"code": 503,
						"message": "Device not opened",
						"opened": False,
						"step": "isOpened",
						"layer": LAYER_LINK,
						"where": LAYER_LINK,
						"what_to_do_next": next_action_for_layer(LAYER_LINK),
					}

				attempts = (
					conf.RECONNECT_MAX_ATTEMPTS
					if max_attempts is None
					else max(1, int(max_attempts))
				)
				delay = conf.RECONNECT_BASE_DELAY_SEC
				last_err = None
				for attempt in range(1, attempts + 1):
					# Best-effort close before reopen (driver may already be closed)
					try:
						if hasattr(self.fptr, "close"):
							self.fptr.close()
					except Exception as close_exc:
						log.debug("fptr.close before reconnect: %s", close_exc)

					# Re-apply USB|TCP settings before each open (F-CONN-03)
					ok, apply_err = self._apply_port_settings()
					if not ok:
						last_err = apply_err
						log.error(
							"applySingleSettings before open failed (attempt %s/%s): %s",
							attempt,
							attempts,
							(apply_err or {}).get("message"),
						)
						if attempt < attempts:
							time.sleep(delay)
							delay = min(delay * 2, conf.RECONNECT_MAX_DELAY_SEC)
						continue

					result = self.fptr.open()
					error_code = self.fptr.errorCode()
					error_description = self.fptr.errorDescription()
					opened = self.fptr.isOpened() != 0

					if opened and (result == 0 or error_code == 0):
						try:
							self.fptr.enableOfdChannel()
						except Exception as ofd_exc:
							log.warning("enableOfdChannel after reconnect: %s", ofd_exc)
						log.info(
							"Device reconnected on attempt %s/%s (mode=%s)",
							attempt,
							attempts,
							self._connection_mode(),
						)
						return {
							"code": 200,
							"message": "Connection successful",
							"opened": True,
							"attempt": attempt,
							"connection_mode": self._connection_mode(),
						}

					# Explicit error-4 class logging for ops
					is_err4 = (
						self._is_port_unavailable(error_code)
						or not opened
						or error_code == IFptr.LIBFPTR_ERROR_PORT_NOT_AVAILABLE
					)
					layer = LAYER_LINK if is_err4 else map_error_to_layer(
						error_code, step="reconnect", context="reconnect"
					)
					last_err = build_failure_record(
						layer=layer,
						step="reconnect",
						error_code=error_code,
						error_description=error_description,
						message=(
							f"Port unavailable / not opened (attempt {attempt}/"
							f"{attempts}): {error_description}"
						),
						context="reconnect",
						override_layer=LAYER_LINK if is_err4 else None,
					)
					remember_failure(last_err)
					log.error(
						"Reconnect attempt %s/%s failed: error_code=%s desc=%s "
						"isOpened=%s layer=%s mode=%s; backing off %.1fs",
						attempt,
						attempts,
						error_code,
						error_description,
						self.fptr.isOpened(),
						layer,
						self._connection_mode(),
						delay,
					)
					if attempt < attempts:
						time.sleep(delay)
						delay = min(delay * 2, conf.RECONNECT_MAX_DELAY_SEC)

				hint = (last_err or {}).get("what_to_do_next")
				if not hint:
					hint = (
						"Check Driver TCP target (Orange Pi → KKT) IP/port."
						if self._connection_mode() == "tcp"
						else "Check USB cable/power and usbcore.autosuspend=-1."
					)
				payload = {
					"code": 500,
					"message": (last_err or {}).get(
						"message", "Failed to open fiscal printer connection"
					),
					"error_code": (last_err or {}).get("error_code"),
					"error_description": (last_err or {}).get("error_description"),
					"step": "reconnect",
					"layer": LAYER_LINK,
					"where": LAYER_LINK,
					"what_to_do_next": hint,
					"opened": False,
					"connection_mode": self._connection_mode(),
				}
				return payload
			except Exception as e:
				record = build_failure_record(
					step="reconnect",
					message=str(e),
					error_description=str(e),
					context="reconnect",
					override_layer=LAYER_LINK,
				)
				remember_failure(record)
				log.error("ensure_connected raised: %s", e, exc_info=True)
				return {
					"code": 500,
					"message": "Failed to open fiscal printer connection",
					"step": "reconnect",
					"layer": LAYER_LINK,
					"where": LAYER_LINK,
					"what_to_do_next": record["what_to_do_next"],
					"opened": False,
				}

	def _cancel_open_receipt(self, app=None):
		"""Cancel an opened receipt that cannot be completed (ATOL #cancel-receipt)."""
		try:
			result = self.fptr.cancelReceipt()
			error_code = self.fptr.errorCode()
			if app is not None:
				app.logger.warning(
					"cancelReceipt result=%s error_code=%s desc=%s",
					result,
					error_code,
					self.fptr.errorDescription(),
				)
			return result == 0 and error_code == 0
		except Exception as exc:
			if app is not None:
				app.logger.error("cancelReceipt raised: %s", exc)
			return False

	def _ensure_document_closed(self, app, timeout_sec=None):
		"""After closeReceipt: checkDocumentClosed; cancel if still open (ATOL #check-document-closure)."""
		if timeout_sec is None:
			timeout_sec = conf.DOCUMENT_CLOSE_TIMEOUT_SEC
		deadline = time.monotonic() + timeout_sec
		while time.monotonic() < deadline:
			result = self.fptr.checkDocumentClosed()
			if result >= 0:
				break
			app.logger.warning(
				"checkDocumentClosed waiting: %s", self.fptr.errorDescription()
			)
			time.sleep(0.5)
		else:
			self._cancel_open_receipt(app)
			err = self._native_error("checkDocumentClosed")
			err["code"] = 504
			err["message"] = "Timeout waiting for document closure"
			return err

		if not self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_CLOSED):
			self._cancel_open_receipt(app)
			return {
				**self._native_error("checkDocumentClosed"),
				"message": "Document not closed; receipt cancelled",
			}

		if not self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_PRINTED):
			print_deadline = time.monotonic() + timeout_sec
			while time.monotonic() < print_deadline:
				result = self.fptr.continuePrint()
				if result >= 0 and self.fptr.errorCode() == 0:
					break
				app.logger.warning(
					"continuePrint waiting: %s", self.fptr.errorDescription()
				)
				time.sleep(0.5)
			else:
				err = self._native_error("continuePrint")
				err["code"] = 504
				err["message"] = "Timeout continuing document print"
				return err
		return None

	def open_connection(self, *, max_attempts=None):
		"""
		Open (or reconnect) the fiscal printer (USB or TCP per conf).
		Pass max_attempts=1 for boot/diagnostics one-shot open (no full F-CONN-04 ladder).
		"""
		return self.ensure_connected(max_attempts=max_attempts)

	def is_device_opened(self):
		"""Best-effort open flag for /health (no reconnect)."""
		with self._lock:
			try:
				opened = self.fptr.isOpened() != 0
				return {
					"code": 200 if opened else 503,
					"opened": opened,
					"error_code": self.fptr.errorCode(),
					"error_description": self.fptr.errorDescription(),
				}
			except Exception as e:
				_log.error("is_device_opened raised: %s", e, exc_info=True)
				return {
					"code": 503,
					"opened": False,
					"message": "Device status check failed",
				}

	def library_status(self):
		"""Diagnostics step 2: library object loadable (no sell receipt)."""
		try:
			# IFptr constructed in __init__; presence of settings API is enough signal
			_ = self.fptr
			model = None
			try:
				# Touch a harmless setting read path if available
				model = IFptr.LIBFPTR_MODEL_ATOL_AUTO
			except Exception:
				pass
			return {
				"code": 200,
				"loadable": True,
				"library_path": conf.get_config().get("library_path") or conf.LIBRARY_PATH,
				"model_constant": model,
				"connection_mode": self._connection_mode(),
			}
		except Exception as e:
			return {"code": 500, "loadable": False, "message": str(e)}

	def get_fn_ofd_status(self, *, reconnect=True):
		"""
		Best-effort FN/OFD status (diagnostics step 5).
		Read-only: FNDT_FN_INFO / FNDT_OFD_EXCHANGE_STATUS / FNDT_ERRORS.
		reconnect=False skips open()/backoff (diagnostics after a one-shot open).
		"""
		with self._lock:
			try:
				conn = self.ensure_connected(reconnect=reconnect)
				if conn.get("code") != 200:
					conn["layer"] = conn.get("layer", LAYER_LINK)
					return conn

				payload = {"code": 200, "fn": {}, "ofd": {}, "errors": {}}

				self.fptr.setParam(
					IFptr.LIBFPTR_PARAM_FN_DATA_TYPE, IFptr.LIBFPTR_FNDT_FN_INFO
				)
				result = self.fptr.fnQueryData()
				if result == 0 and self.fptr.errorCode() == 0:
					payload["fn"] = {
						"serial": self.fptr.getParamString(
							getattr(IFptr, "LIBFPTR_PARAM_FN_SERIAL_NUMBER", 0)
						)
						if hasattr(self.fptr, "getParamString")
						else None,
						"memory_overflow": bool(
							self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_FN_MEMORY_OVERFLOW)
						)
						if hasattr(self.fptr, "getParamBool")
						else None,
						"resource_exhausted": bool(
							self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_FN_RESOURCE_EXHAUSTED)
						)
						if hasattr(self.fptr, "getParamBool")
						else None,
					}
					if payload["fn"].get("memory_overflow") or payload["fn"].get(
						"resource_exhausted"
					):
						payload["code"] = 500
						payload["layer"] = LAYER_FN_OFD
						payload["message"] = "FN memory/resource exhausted"
						payload["where"] = LAYER_FN_OFD
						return payload
				else:
					# Soft-fail: still try OFD exchange
					payload["fn"]["query_error"] = self.fptr.errorDescription()

				self.fptr.setParam(
					IFptr.LIBFPTR_PARAM_FN_DATA_TYPE,
					IFptr.LIBFPTR_FNDT_OFD_EXCHANGE_STATUS,
				)
				result = self.fptr.fnQueryData()
				if result == 0 and self.fptr.errorCode() == 0:
					payload["ofd"] = {
						"exchange_status": self.fptr.getParamInt(
							IFptr.LIBFPTR_PARAM_OFD_EXCHANGE_STATUS
						),
						"documents_count": self.fptr.getParamInt(
							IFptr.LIBFPTR_PARAM_DOCUMENTS_COUNT
						),
					}
				else:
					payload["ofd"]["query_error"] = self.fptr.errorDescription()

				self.fptr.setParam(
					IFptr.LIBFPTR_PARAM_FN_DATA_TYPE, IFptr.LIBFPTR_FNDT_ERRORS
				)
				result = self.fptr.fnQueryData()
				if result == 0 and self.fptr.errorCode() == 0:
					payload["errors"] = {
						"network_error": self.fptr.getParamInt(
							IFptr.LIBFPTR_PARAM_NETWORK_ERROR
						),
						"network_error_text": self.fptr.getParamString(
							IFptr.LIBFPTR_PARAM_NETWORK_ERROR_TEXT
						)
						if hasattr(self.fptr, "getParamString")
						else None,
						"ofd_error": self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_OFD_ERROR)
						if hasattr(IFptr, "LIBFPTR_PARAM_OFD_ERROR")
						else None,
						"fn_error": self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_FN_ERROR)
						if hasattr(IFptr, "LIBFPTR_PARAM_FN_ERROR")
						else None,
					}
					net_err = payload["errors"].get("network_error") or 0
					ofd_err = payload["errors"].get("ofd_error") or 0
					fn_err = payload["errors"].get("fn_error") or 0
					if net_err or ofd_err or fn_err:
						payload["code"] = 500
						payload["layer"] = LAYER_FN_OFD
						payload["message"] = "FN/OFD exchange reports errors"
						payload["where"] = LAYER_FN_OFD
						return payload

				return payload
			except Exception as e:
				return {
					"code": 500,
					"message": str(e),
					"layer": LAYER_FN_OFD,
					"where": LAYER_FN_OFD,
					"step": "fn_ofd",
				}

	def get_device_params(self):
		with self._lock:
			try:
				conn = self.ensure_connected()
				if conn.get("code") != 200:
					return conn

				self.fptr.setParam(IFptr.LIBFPTR_PARAM_DATA_TYPE, IFptr.LIBFPTR_DT_STATUS)
				result = self.fptr.queryData()
				ok, err = self._call_ok(result, "queryData")
				if not ok:
					return err

				operatorId = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_OPERATOR_ID)
				modelName = self.fptr.getParamString(IFptr.LIBFPTR_PARAM_MODEL_NAME)
				firmwareVersion = self.fptr.getParamString(IFptr.LIBFPTR_PARAM_UNIT_VERSION)
				shiftStatus = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_STATE)
				shiftNumber = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_NUMBER)
				recordsID = self.fptr.getParamString(IFptr.LIBFPTR_PARAM_RECORDS_ID)

				return {
					"code": 200,
					"status": {
						"operator_id": operatorId,
						"model_name": modelName,
						"firmwareVersion": firmwareVersion,
						"shiftStatus": shiftStatus,
						"shiftNumber": shiftNumber,
						"test": recordsID,
					},
				}
			except Exception as e:
				return {"code": 500, "message": str(e)}

	def get_shift_status(self, *, reconnect=True):
		"""
		Query shift state. Default reconnect=True (fiscal ops / F-CONN-04).
		reconnect=False: best-effort query only if already open — no open()/backoff
		(for /health so a dropped link cannot starve job1 under RLock).
		"""
		with self._lock:
			try:
				if reconnect:
					conn = self.ensure_connected()
					if conn.get("code") != 200:
						return conn
				elif self.fptr.isOpened() == 0:
					return {
						"code": 503,
						"message": "Device not opened",
						"opened": False,
						"step": "get_shift_status",
						"layer": LAYER_LINK,
						"where": LAYER_LINK,
						"what_to_do_next": next_action_for_layer(LAYER_LINK),
					}

				self.fptr.setParam(IFptr.LIBFPTR_PARAM_DATA_TYPE, IFptr.LIBFPTR_DT_SHIFT_STATE)
				result = self.fptr.queryData()
				ok, err = self._call_ok(result, "get_shift_status")
				if not ok:
					return err

				shiftStatus = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_STATE)
				status = ShiftSatus(shiftStatus)

				if status == ShiftSatus.OPEN:
					return {"code": 200, "shift": "OPEN"}
				elif status == ShiftSatus.CLOSED:
					return {"code": 400, "shift": "CLOSED"}
				elif status == ShiftSatus.EXPIRED:
					return {"code": 450, "shift": "EXPIRED"}
				return {"code": 500, "message": f"Unknown shift status: {shiftStatus}"}
			except Exception as e:
				_log.error("get_shift_status raised: %s", e, exc_info=True)
				return {
					"code": 500,
					"message": "Failed to query shift status",
					"layer": "KKT",
					"step": "get_shift_status",
				}

	def close_shift(self, timeout_sec=None):
		"""Close shift (close-shift report) with hard timeout (F-FISC-05). Default 120s."""
		if timeout_sec is None:
			timeout_sec = conf.SHIFT_CLOSE_TIMEOUT_SEC
		deadline = time.monotonic() + timeout_sec

		with self._lock:
			try:
				conn = self.ensure_connected()
				if conn.get("code") != 200:
					return conn

				self.fptr.setParam(IFptr.LIBFPTR_PARAM_REPORT_TYPE, IFptr.LIBFPTR_RT_CLOSE_SHIFT)
				result = self.fptr.report()
				# Nonzero may mean busy / still closing; poll until CLOSED or timeout
				if result != 0 and self.fptr.errorCode() != 0:
					pass

				while time.monotonic() < deadline:
					shift_status = self.get_shift_status()
					if shift_status.get("code") == 400:
						self.fptr.beep()
						return {"code": 201, "message": "Closed successfully"}
					if shift_status.get("code") == 450:
						# Still expired — re-issue close-shift report
						self.fptr.setParam(
							IFptr.LIBFPTR_PARAM_REPORT_TYPE, IFptr.LIBFPTR_RT_CLOSE_SHIFT
						)
						self.fptr.report()
					elif shift_status.get("code") == 200:
						# Unexpectedly still open after report; retry close once per poll
						self.fptr.setParam(
							IFptr.LIBFPTR_PARAM_REPORT_TYPE, IFptr.LIBFPTR_RT_CLOSE_SHIFT
						)
						self.fptr.report()
					elif shift_status.get("code") not in (200, 400, 450):
						return shift_status
					time.sleep(2)

				return {
					"code": 504,
					"message": f"Shift close timed out after {timeout_sec}s",
					"retryable": True,
					"layer": "KKT",
					"step": "close_shift",
				}
			except Exception as e:
				return {"code": 500, "message": str(e)}

	def print_check(self, check_data, app):
		"""
		Fail-stop receipt sequence (F-FISC-01..04):
		openReceipt → registration → payment → receiptTax → receiptTotal → closeReceipt.
		On failure after open: cancelReceipt. Never return 201 if any step failed.
		"""
		check_id = check_data.get("id")
		with self._lock:
			receipt_opened = False
			try:
				conn = self.ensure_connected(logger=getattr(app, "logger", None))
				if conn.get("code") != 200:
					app.logger.error("Device not connected before print: %s", conn)
					return conn

				app.logger.info("The beginning of creating a receipt at the checkout")

				price = _money(check_data["price"])
				quantity = _money(check_data.get("quiantity", 1))
				payment_sum = _money(check_data["sum"])

				self.fptr.setParam(IFptr.LIBFPTR_PARAM_RECEIPT_TYPE, IFptr.LIBFPTR_RT_SELL)
				result = self.fptr.openReceipt()
				ok, err = self._call_ok(result, "openReceipt", check_id=check_id)
				if not ok:
					app.logger.error("Error open: %s", err)
					return err
				receipt_opened = True
				app.logger.info("Check open")

				self.fptr.setParam(IFptr.LIBFPTR_PARAM_COMMODITY_NAME, str(check_data["name"]))
				self.fptr.setParam(IFptr.LIBFPTR_PARAM_PRICE, price)
				self.fptr.setParam(IFptr.LIBFPTR_PARAM_QUANTITY, quantity)
				self.fptr.setParam(IFptr.LIBFPTR_PARAM_TAX_TYPE, IFptr.LIBFPTR_TAX_NO)
				self.fptr.setParam(1212, 4)
				self.fptr.setParam(1214, 4)

				result = self.fptr.registration()
				ok, err = self._call_ok(result, "registration", check_id=check_id)
				if not ok:
					app.logger.error("Error registration: %s", err)
					self._cancel_open_receipt(app)
					return err
				app.logger.info("Check registration")

				# "0" = cash; anything else = electronic (F-FISC-07). Tax stays LIBFPTR_TAX_NO.
				if str(check_data["type"]) == "0":
					self.fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_TYPE, IFptr.LIBFPTR_PT_CASH)
				else:
					self.fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_TYPE, IFptr.LIBFPTR_PT_ELECTRONICALLY)

				self.fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_SUM, payment_sum)
				result = self.fptr.payment()
				ok, err = self._call_ok(result, "payment", check_id=check_id)
				if not ok:
					app.logger.error("Error payment: %s", err)
					self._cancel_open_receipt(app)
					return err
				app.logger.info("Check payment")

				self.fptr.setParam(IFptr.LIBFPTR_PARAM_TAX_TYPE, IFptr.LIBFPTR_TAX_NO)
				result = self.fptr.receiptTax()
				ok, err = self._call_ok(result, "receiptTax", check_id=check_id)
				if not ok:
					app.logger.error("Error receiptTax: %s", err)
					self._cancel_open_receipt(app)
					return err
				app.logger.info("Check receiptTax")

				result = self.fptr.receiptTotal()
				ok, err = self._call_ok(result, "receiptTotal", check_id=check_id)
				if not ok:
					app.logger.error("Error receiptTotal: %s", err)
					self._cancel_open_receipt(app)
					return err
				app.logger.info("Check receiptTotal")

				result = self.fptr.closeReceipt()
				ok, err = self._call_ok(result, "closeReceipt", check_id=check_id)
				if not ok:
					app.logger.error("Error closeReceipt: %s", err)
					# Document may still be open — checkDocumentClosed / cancel (F-FISC-03)
					closure_err = self._ensure_document_closed(app)
					if closure_err is not None:
						if check_id is not None:
							closure_err["check_id"] = check_id
						return closure_err
					# Document closed despite closeReceipt error — still never return success
					return err
				app.logger.info("Check closeReceipt")

				closure_err = self._ensure_document_closed(app)
				if closure_err is not None:
					app.logger.error("Error after close: %s", closure_err)
					if check_id is not None:
						closure_err["check_id"] = check_id
					return closure_err

				receipt_opened = False
				self.fptr.beep()
				return {"code": 201}
			except ValueError as e:
				if receipt_opened:
					self._cancel_open_receipt(app)
				return {
					"code": 400,
					"message": str(e),
					"layer": "APP",
					"step": "validation",
					"check_id": check_id,
				}
			except Exception as e:
				if receipt_opened:
					self._cancel_open_receipt(app)
				app.logger.error("print_check raised: %s", e, exc_info=True)
				return {
					"code": 500,
					"message": "Print failed due to an internal error",
					"layer": "UNKNOWN",
					"check_id": check_id,
				}

	def readNextRecord(self, recordID):
		with self._lock:
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_RECORDS_ID, recordID)
			return self.fptr.readNextRecord()

	def readLastReciept(self):
		with self._lock:
			conn = self.ensure_connected()
			if conn.get("code") != 200:
				return conn

			self.fptr.setParam(IFptr.LIBFPTR_PARAM_FN_DATA_TYPE, IFptr.LIBFPTR_FNDT_LAST_RECEIPT)
			result = self.fptr.fnQueryData()
			ok, err = self._call_ok(result, "readLastReciept", context="fn_ofd")
			if not ok:
				return err

			checkNumber = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_DOCUMENT_NUMBER)
			json_data = json.dumps({
				"type": "getFnDocument",
				"fiscalDocumentNumber": checkNumber,
				"withRawData": True,
			})
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_JSON_DATA, json_data)
			result = self.fptr.processJson()
			ok, err = self._call_ok(result, "processJson")
			if not ok:
				return err
			return self.fptr.getParamString(IFptr.LIBFPTR_PARAM_JSON_DATA)

	def checkClose(self):
		"""Ensure document closed after closeReceipt; cancel if still open."""
		with self._lock:
			deadline = time.monotonic() + conf.DOCUMENT_CLOSE_TIMEOUT_SEC
			while time.monotonic() < deadline:
				if self.fptr.checkDocumentClosed() >= 0:
					break
				time.sleep(0.5)
			else:
				self._cancel_open_receipt()
				return {"code": 504, "message": "Timeout waiting for document closure"}

			if not self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_CLOSED):
				self._cancel_open_receipt()
				return {"code": 500, "message": "Document not closed; receipt cancelled"}

			if not self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_PRINTED):
				print_deadline = time.monotonic() + conf.DOCUMENT_CLOSE_TIMEOUT_SEC
				while time.monotonic() < print_deadline:
					if self.fptr.continuePrint() >= 0 and self.fptr.errorCode() == 0:
						break
					time.sleep(0.5)
				else:
					return {"code": 504, "message": "Timeout continuing document print"}
			return {"code": 200}

	def openShift(self, timeout_sec=None):
		"""Open shift with hard timeout (F-FISC-05 / AC-4). Default 120s."""
		if timeout_sec is None:
			timeout_sec = conf.SHIFT_OPEN_TIMEOUT_SEC
		deadline = time.monotonic() + timeout_sec

		with self._lock:
			try:
				conn = self.ensure_connected()
				if conn.get("code") != 200:
					return conn

				result = self.fptr.openShift()
				# Nonzero may mean already opening / transient; poll status until OPEN or timeout
				if result != 0 and self.fptr.errorCode() != 0:
					# Still poll — some firmwares report busy while opening
					pass

				while time.monotonic() < deadline:
					# Nested RLock OK
					shift_status = self.get_shift_status()
					if shift_status.get("code") == 200:
						return shift_status
					if shift_status.get("code") == 400:
						self.fptr.openShift()
					elif shift_status.get("code") == 450:
						# Caller should close expired shift first; surface clearly
						return {
							"code": 450,
							"message": "Shift expired; close shift before opening",
						}
					elif shift_status.get("code") not in (200, 400, 450):
						return shift_status
					time.sleep(2)

				return {
					"code": 504,
					"message": f"Shift open timed out after {timeout_sec}s",
					"retryable": True,
					"layer": "KKT",
					"step": "openShift",
				}
			except Exception as e:
				return {"code": 500, "message": str(e)}

	def info(self):
		with self._lock:
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_DATA_TYPE, IFptr.LIBFPTR_DT_SHIFT_STATE)
			self.fptr.queryData()

			state = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_STATE)
			number = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_NUMBER)
			dateTime = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_DATE_TIME)
			print(state)
			print(number)
			print(dateTime)

			self.fptr.setParam(IFptr.LIBFPTR_PARAM_FN_DATA_TYPE, IFptr.LIBFPTR_FNDT_ERRORS)
			self.fptr.fnQueryData()

			print(self.fptr.getParamDateTime(IFptr.LIBFPTR_PARAM_DATE_TIME))
			print(self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_NETWORK_ERROR))
			print(self.fptr.getParamString(IFptr.LIBFPTR_PARAM_NETWORK_ERROR_TEXT))

			self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 273)
			self.fptr.readDeviceSetting()
			print(self.fptr.getParamString(IFptr.LIBFPTR_PARAM_SETTING_VALUE))

			self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 274)
			self.fptr.readDeviceSetting()
			print(self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SETTING_VALUE))

			self.fptr.setParam(IFptr.LIBFPTR_PARAM_FN_DATA_TYPE, IFptr.LIBFPTR_FNDT_OFD_EXCHANGE_STATUS)
			self.fptr.fnQueryData()

			print(self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_OFD_EXCHANGE_STATUS))
			print(self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_DOCUMENTS_COUNT))

	def lastOper(self):
		with self._lock:
			self.fptr.getLastDocumentJournal()
			document = self.fptr.getParamByteArray(IFptr.LIBFPTR_PARAM_TLV_LIST)

			pos = 0
			while pos < len(document):
				tag = document[pos] | (document[pos + 1] << 8)
				length = document[pos + 2] | (document[pos + 3] << 8)
				pos += 4
				value = document[pos:pos + length]
				pos += length
				print(tag)
				print(value)


cashier_service = CashierService()
