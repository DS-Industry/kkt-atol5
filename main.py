from flask import Flask, request, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
from flask_apscheduler import APScheduler
from cashierService import cashier_service
import time


scheduler = APScheduler()
cashier_service.open_connection()


@scheduler.task("interval", id="do_job_1", seconds=3, misfire_grace_time=900, max_instances=1)
def job1():
    with app.app_context():
        checks = Check.query.filter_by(isProcessed=False).all()
        for check in checks:
            check.isProcessed = True
            db.session.commit()
            openStatus = cashier_service.openShift()
            checkData = {
                "name": check.name,
                "price": check.sum,
                "sum": check.sum,
                "quiantity": 1,
                "type": check.type
            }
            cashier_service.print_check(checkData)
            result = cashier_service.readLastReciept()
            text = result.strip().strip('"')
            data = json.loads(text)
            check.qr=data["documentTLV"]["qr"]
            check.isQr=True
            db.session.commit()
            shiftStatus = cashier_service.get_shift_status()
            if shiftStatus["code"] == 200:
                res = cashier_service.close_shift()
                print(res)
            


app = Flask(__name__)

# Configure SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///checks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SCHEDULER_API_ENABLED'] = True

db = SQLAlchemy(app)


class Check(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    bay = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=True)  # This can be set later or added from headers
    quantity = db.Column(db.Integer, nullable=True)  # Same for quantity
    type = db.Column(db.String(50), nullable=False)
    sum = db.Column(db.Float, nullable=False)
    isProcessed = db.Column(db.Boolean, default=False)
    isQr = db.Column(db.Boolean, default=False)
    dateCreated = db.Column(db.DateTime, default=datetime.utcnow)
    dateProcessed = db.Column(db.DateTime, nullable=True)
    qr = db.Column(db.String(255), nullable=True)

def find_actual_check(bay_value):
    while True:
        time.sleep(5)
        db.session.rollback()
        check = Check.query.filter_by(isQr=True, bay=bay_value).first()
        if check:
            qr = check.qr
            print(qr)
            db.session.delete(check)
            db.session.commit()
            return qr
        
def create_check(name, sum, type):
    openStatus = cashier_service.openShift()
    checkData = {
       "name": name,
        "price": sum,
        "sum": sum,
        "quiantity": 1,
        "type": type
    }
    cashier_service.print_check(checkData)
    result = cashier_service.readLastReciept()
    text = result.strip().strip('"')
    data = json.loads(text)
    qr=data["documentTLV"]["qr"]
    return qr

@app.route('/get-checks', methods=['GET'])
def get_checks():
    checks = Check.query.all()
    checks_data = []
    for check in checks:
        checks_data.append({
            'id': check.id,
            'name': check.name,
            'bay': check.bay,
            'price': check.price,
            'quantity': check.quantity,
            'type': check.type,
            'sum': check.sum,
            'isProcessed': check.isProcessed,
            'dateCreated': check.dateCreated,
            'dateProcessed': check.dateProcessed,
            'qr': check.qr,
            'isQr': check.isQr
        })
    return jsonify(checks_data), 200


@app.route('/create-check', methods=['POST'])
def create_check():
    try:
        # Extract the JSON string from headers
        data_str = request.headers.get('Data')  # Expecting a header called 'Data'

        if not data_str:
            return jsonify({"error": "No data provided in headers"}), 400

        # Parse the JSON string to a Python object
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON format"}), 400

        # Extract required fields
        name = data.get('name')
        bay = data.get('bay')
        sum_value = data.get('sum')
        type_value = data.get('type')

        # Validate required fields
        if not all([name, bay, sum_value, type_value]):
            return jsonify({"error": "Missing required fields"}), 400

        # Create a new check object
        new_check = Check(
            name=name,
            bay=bay,
            sum=sum_value,
            type=type_value
        )

        # Add and commit the new check to the database
        db.session.add(new_check)
        db.session.commit()

        qr = find_actual_check(new_check.bay)

        return jsonify({"message": "Check created successfully", "qr": qr}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

#print(cashier_service.print_check(checkData))
#cashier_service.readLastReciept()
#cashier_service.checkClose()
#print(cashier_service.get_device_params())
#result = cashier_service.readLastReciept()
#print(result)
#cashier_service.lastOper()
#if  shiftStatus["code"] == 200:
#    cashier_service.close_shift()

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    scheduler.init_app(app)
    scheduler.start()
    app.run(host='0.0.0.0')

    #r = cashier_service.print_check(checkData)
    #print(r)
    #result = cashier_service.readLastReciept()
    #print(result)
    #cashier_service.info()
    #cashier_service.openShift()
    #r = cashier_service.print_check(checkData)
    #cashier_service.readLastReciept()
    #print(r)
    #time.sleep(10)
    #cashier_service.info()
    #cashier_service.checkClose()
    #shiftStatus = cashier_service.get_shift_status()
    #if shiftStatus["code"] == 200:
    #    res = cashier_service.close_shift()
    #    time.sleep(10)
    #    print(res)
    

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
