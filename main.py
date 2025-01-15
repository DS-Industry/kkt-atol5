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
            shiftStatus = cashier_service.get_shift_status()
            if shiftStatus["code"] == 450:
                res = cashier_service.close_shift()
                openStatus = cashier_service.openShift()
            elif shiftStatus["code"] != 200:
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
            check.qr = data["documentTLV"]["qr"]
            check.isQr = True
            db.session.commit()


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
    qr = data["documentTLV"]["qr"]
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
        nameType = data.get('name')
        bay = data.get('bay')
        sum_value = data.get('sum')
        type_value = data.get('type')
        name = ''

        if nameType == '1':
            name = 'Робот ' + bay
        elif nameType == '2':
            name = 'Пост ' + bay
        elif nameType == '0':
            name = 'Пылесос ' + bay

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
        print('send' + qr)

        return jsonify({"message": "Check created successfully", "qr": qr}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    scheduler.init_app(app)
    scheduler.start()
    app.run(host='0.0.0.0')
