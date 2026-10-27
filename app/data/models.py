from datetime import datetime

from app.data.db import db

# Queue lifecycle (F-Q-01): pending → printing → done | failed
STATUS_PENDING = "pending"
STATUS_PRINTING = "printing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

class Check(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    bay = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=True)
    quantity = db.Column(db.Integer, nullable=True)
    type = db.Column(db.String(50), nullable=False)
    sum = db.Column(db.Float, nullable=False)
    # Legacy flags kept during transition (AGENTS.md §6 / F-Q-01)
    isProcessed = db.Column(db.Boolean, default=False)
    isQr = db.Column(db.Boolean, default=False)
    dateCreated = db.Column(db.DateTime, default=datetime.utcnow)
    dateProcessed = db.Column(db.DateTime, nullable=True)
    qr = db.Column(db.String(255), nullable=True)
    fiscal_document = db.Column(db.Text, nullable=True)
    # Schema change (explicit): queue lifecycle + failure reason (Phase A)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    error_message = db.Column(db.String(500), nullable=True)
    error_code = db.Column(db.String(50), nullable=True)
    # Schema change (explicit, Phase B / F-DIAG-01, F-DIAG-07): fault isolation fields
    # ADDITIVE only — do not rename typo fields (quiantity/isProcessed/dateProccesed legacy).
    layer = db.Column(db.String(20), nullable=True)
    step = db.Column(db.String(50), nullable=True)
    error_description = db.Column(db.String(500), nullable=True)


class FiscalOutbox(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    payload = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QRDisplayDelivery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    category = db.Column(db.String(10), nullable=False, index=True)
    bay = db.Column(db.String(50), nullable=False)
    qr = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    host = db.Column(db.String(100), nullable=True)
    error = db.Column(db.String(500), nullable=True)
