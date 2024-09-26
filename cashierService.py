import sys
import os
import json
import logging
import time

from libfptr10 import IFptr
from conf import LIBRARY_PATH
import enum

class ShiftSatus (enum.Enum):
	OPEN = 1
	CLOSED = 0
	EXPIRED = 2

class CashierService:
	def __init__(self):
		self._initialize_device()
	

	def _initialize_device(self):
		print('tyt')
		self.fptr = IFptr(LIBRARY_PATH)
		self.fptr.setSingleSetting(IFptr.LIBFPTR_SETTING_MODEL, str(IFptr.LIBFPTR_MODEL_ATOL_AUTO))
		self.fptr.setSingleSetting(IFptr.LIBFPTR_SETTING_PORT, str(IFptr.LIBFPTR_PORT_USB))
		self.fptr.setSingleSetting(IFptr.LIBFPTR_SETTING_OFD_CHANNEL, str(IFptr.LIBFPTR_OFD_CHANNEL_AUTO))
		self.fptr.applySingleSettings()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 12)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 3)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 16)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 182)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "СИС. АДМИНИСТРАТОР")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 236)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 4800)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 244)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "ПЛАТ.КАРТОЙ")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 245)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "ТАРОЙ")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 246)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "КРЕДИТОМ")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 247)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "ТИП 9")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 248)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "ТИП 10")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 253)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 2)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 254)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 2)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 255)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 2)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 256)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 2)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 257)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 2)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 269)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "Ssid")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 270)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "Pswd")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 271)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 5)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 272)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 4)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 273)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "k-server.1-ofd.ru")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 274)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 7777)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 276)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 5)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 278)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "ks.atol.ru")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 279)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 80)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 281)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 5)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 284)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "0.0.0.0")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 292)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 295)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 255)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 300)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 325)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 326)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "0.0.0.0")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 327)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "0.0.0.0")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 328)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "0.0.0.0")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 329)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 5555)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 331)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 336)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 15)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 337)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 2)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 338)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 347)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 255)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 348)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 255)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 350)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 376)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 377)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "0000")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 383)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 385)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 39)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 4)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 46)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 50)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 32)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 55)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 56)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 57)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 58)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 1)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 71)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "192.168.53.130")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 72)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "255.255.255.0")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 73)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, "192.168.53.100")
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 74)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 5555)
		self.fptr.writeDeviceSetting()
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_ID, 8)
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_SETTING_VALUE, 40)
		self.fptr.writeDeviceSetting()
		self.fptr.commitSettings()
		print(self.fptr.getSettingsStr())


	def open_connection(self):
		try:
			self.fptr.open()
			print(self.fptr.isOpened())
			if self.fptr.isOpened() == 0:
				return { "code": 500, "message": "No conection to the printer"}
			else:
				self.fptr.enableOfdChannel()
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
			recordsID = self.fptr.getParamString(IFptr.LIBFPTR_PARAM_RECORDS_ID)

			return {
				"code": 200,
				"status": {
					"operator_id": operatorId,
					"model_name": modelName,
					"firmwareVersion": firmwareVersion,
					"shiftStatus": shiftStatus,
					"shiftNumber": shiftNumber,
					"test": recordsID
				}
			}

		except Exception as e:
			return {"code": 500, "message": str(e)}

	def get_shift_status(self):
		try:
			self.fptr.setParam(IFptr.LIBFPTR_PARAM_DATA_TYPE, IFptr.LIBFPTR_DT_SHIFT_STATE)
			self.fptr.queryData()

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
			#self.fptr.setParam(IFptr.LIBFPTR_PARAM_RECEIPT_ELECTRONICALLY, True)
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

	def readNextRecord(self, recordID):
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_RECORDS_ID, recordID)
		
		return self.fptr.readNextRecord()
		
	def readLastReciept(self):
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_FN_DATA_TYPE, IFptr.LIBFPTR_FNDT_LAST_RECEIPT)
		self.fptr.fnQueryData()
		checkNumber = self.fptr.getParamInt(IFptr.LIBFPTR_PARAM_DOCUMENT_NUMBER)
		print(checkNumber)
		json_data = json.dumps({
			"type" : "getFnDocument", 
			"fiscalDocumentNumber" : checkNumber,
			"withRawData" : True
		})
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_JSON_DATA, json_data)
		self.fptr.processJson()
		result = self.fptr.getParamString(IFptr.LIBFPTR_PARAM_JSON_DATA)
		return result
		
	
	def checkClose(self):
		print(self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_CLOSED))
		print(self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_PRINTED))
		self.fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_TYPE, IFptr.LIBFPTR_PT_ELECTRONICALLY)
		self.fptr.closeReceipt()

		while self.fptr.checkDocumentClosed() < 0:
			print("tyta")
			print(self.fptr.errorDescription())
			continue

		if not self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_CLOSED):
			print('tyty')
			self.fptr.cancelReceipt()
			return
		
		if not self.fptr.getParamBool(IFptr.LIBFPTR_PARAM_DOCUMENT_PRINTED):
			print(self.fptr.continuePrint())
			while self.fptr.continuePrint() < 0:
				print('Error "%s"', self.fptr.errorDescription())
				continue
			
	def openShift(self):
		try:
			self.fptr.openShift()
			while True:
				time.sleep(2)
				shift_status = self.get_shift_status()
				print(shift_status)
				if shift_status["code"] == 400:
					self.fptr.openShift()
				elif shift_status["code"] == 200:
					return shift_status
		except Exception as e:
			return {"code": 500, "message": str(e)}

	def info(self):
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