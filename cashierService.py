import sys
import os
import json
import logging

from libfptr10 import IFptr
from conf import LIBRARY_PATH
import enum

class ShiftSatus (enum.Enum):
	OPEN = 0
	CLOSED = 1
	EXPIRED = 2

class CashierService:
	def __init__(self):
		self._initialize_device()
	

	def _initialize_device(self):
		self.fptr = IFptr(LIBRARY_PATH)
		self.fptr.setSingleSetting(IFptr.LIBFPTR_SETTING_MODEL, str(IFptr.LIBFPTR_MODEL_ATOL_AUTO))
		self.fptr.setSingleSetting(IFptr.LIBFPTR_SETTING_PORT, str(IFptr.LIBFPTR_PORT_USB))
		self.fptr.applySingleSettings()


	def open_connection(self):
		try:
			self.fptr.open()
			if self.fptr.isOpened() == 0:
				return { "code": 500, "message": "No conection to the printer"}
			else:
				return { "code": 200, "message": "Connection successful"}
		except Exception as e:
			return {"code": 500, "message": str(e)}
	
	def get_device_params(self):
		try:
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_DATA_TYPE, IFptr.LIBFPTR_DT_STATUS)
			self.fptr.queryData()


			operatorId = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_OPERATOR_ID)
			modelName = self.fptr.getParamString(IFptr.LIBFPTR_PARAM_MODEL_NAME)
			firmwareVersion = self.fptr.getParamString(IFptr.LIBFPTR_PARAM_UNIT_VERSION)
			shiftStatus = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_STATE)
			shiftNumber = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_NUMBER)

			return {
				"code": 200,
				"status": {
					"operator_id": operatorId,
					"model_name": modelName,
					"firmwareVersion": firmwareVersion,
					"shiftStatus": shiftStatus,
					"shiftNumber": shiftNumber
				}
			}

		except Exception as e:
			return {"code": 500, "message": str(e)}

	def get_shift_status(self):
		try:
			shiftStatus = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_STATE)
			status = ShiftSatus(shiftStatus)

			if status == ShiftSatus.OPEN:
				return { "code": 200 }
			elif status == ShiftSatus.CLOSED:
				return { "code": 400 }
			elif status == ShiftSatus.EXPIRED:
				return { "code": 450 } 
		except Exception as e:
			return {"code": 500, "message": str(e)}

	def close_shift(self):
		try:
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_REPORT_TYPE, IFptr.LIBFPTR_RT_CLOSE_SHIFT)
			self.fptr.report()
			self.fptr.beep()
			return { "code": 201, "message": "Closed successfully" }
		except Exception as e:
			return {"code": 500, "message": str(e)}
	
	def print_check(self, check_data):
		try:
		
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_RECEIPT_TYPE, IFptr.LIBFPTR_RT_SELL)
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_RECEIPT_ELECTRONICALLY, True)
			self.fptr.openReceipt()

			#Add check itmes
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_COMMODITY_NAME, str(check_data["name"]))
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_PRICE, str(check_data["price"]))
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_QUANTITY, str(check_data["quiantity"]))	
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_TAX_TYPE, IFptr.LIBFPTR_TAX_NO)
			payment_type = check_data["type"]

			self.fptr.registration()
			payment_value = IFptr.LIBFPTR_PT_CASH if payment_type == "cash" else IFptr.LIBFPTR_PT_ELECTRONICALLY
		
			#Process payment
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_TYPE, payment_value)
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_SUM, int(check_data["sum"]))
			self.fptr.payment()

					
			#Register tax
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_TAX_TYPE, IFptr.LIBFPTR_TAX_NO)
			self.fptr.receiptTax()
			
			#Register final total
			self.fptr.receiptTotal()
			
			#Close check
			self.fptr.closeReceipt()
			
			
			self.fptr.beep()

			return { "code": 201}
		except Exception as e:
			return {"code": 500, "message": str(e)}


cashier_service = CashierService()