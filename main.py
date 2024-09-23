from cashierService import cashier_service

cashier_service.open_connection()


shiftStatus = cashier_service.get_shift_status()

if  shiftStatus["code"] == 200:
    cashier_service.close_shift()
    

checkData = {
    "name": "Test id",
    "price": 200,
    "sum": 200,
    "quiantity": 1,
    "type": "cash"
}

result = cashier_service.readLastReciept()
print(str(result))



""""
cashier_service.open_connection()
params = cashier_service.get_device_params()

def print_check(fptr, check_data):
	res = 0
	message = "check_data " + str(check_data)
	
	print(message)
	logging.info(message)
	
	#Checking if shift expired
	shiftStatus = fptr.getParamInt(IFptr.LIBFPTR_PARAM_SHIFT_STATE)
	print("STATUS -> " + str(shiftStatus))
	if shiftStatus == 2:
		message = "Closed shift -> siftStatus " + str(shiftStatus)
		print(message)
		fptr.setParam(IFptr.LIBFPTR_PARAM_REPORT_TYPE, IFptr.LIBFPTR_RT_CLOSE_SHIFT)
		fptr.report()
	
	#Open check
	fptr.setParam(IFptr.LIBFPTR_PARAM_RECEIPT_TYPE, IFptr.LIBFPTR_RT_SELL)
	fptr.setParam(IFptr.LIBFPTR_PARAM_RECEIPT_ELECTRONICALLY, True)
	fptr.openReceipt()
	
	message = "status -> opened receipt"
	print(message)
	payment_type = 'cash'
	
	#Add check itmes
	fptr.setParam(IFptr.LIBFPTR_PARAM_COMMODITY_NAME, str(check_data["name"]))
	fptr.setParam(IFptr.LIBFPTR_PARAM_PRICE, str(check_data["price"]))
	fptr.setParam(IFptr.LIBFPTR_PARAM_QUANTITY, str(check_data["quiantity"]))
	fptr.setParam(IFptr.LIBFPTR_PARAM_TAX_TYPE, IFptr.LIBFPTR_TAX_NO)
	payment_type = check_data["type"]
		
		
	fptr.registration()
	
	message = "status -> added receipt items"
	print(message)
	
	payment_value = IFptr.LIBFPTR_PT_CASH if payment_type == "cash" else IFptr.LIBFPTR_PT_ELECTRONICALLY
	
	#Process payment
	fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_TYPE, payment_value)
	fptr.setParam(IFptr.LIBFPTR_PARAM_PAYMENT_SUM, int(check_data["sum"]))
	fptr.payment()
	
	message = "status -> payment completed"
	print(message)
	
	#Register tax
	fptr.setParam(IFptr.LIBFPTR_PARAM_TAX_TYPE, IFptr.LIBFPTR_TAX_NO)
	fptr.receiptTax()
	
	#Register final total
	fptr.receiptTotal()
	
	#Close check
	#fptr.closeReceipt()
	
	message = "status -> check closed"
	print(message)
	
	fptr.beep()
	
	return 1
	
		
	"""







