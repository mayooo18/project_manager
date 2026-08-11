from extensions import db
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    contact = db.Column(db.String(100))
    daily_rate = db.Column(db.Float)
    active = db.Column(db.Boolean, default=True)
    
    payments = db.relationship("Payment", back_populates="worker", cascade="all, delete-orphan")


    work_logs = db.relationship('WorkLog', back_populates='worker', cascade='all, delete-orphan')

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    address = db.Column(db.String(200))
    start_date = db.Column(db.Date)
    status = db.Column(db.String(50), default="Active")
    google_folder_id = db.Column(db.String(200), nullable=True)
    google_doc_id = db.Column(db.String(200), nullable=True)

    work_logs = db.relationship('WorkLog', back_populates='project', cascade='all, delete-orphan')
    files = db.relationship("ProjectFile", backref="project", cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='project', cascade='all, delete-orphan')
    incomes = db.relationship('Income', backref='incomes', cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='project_payments', cascade='all, delete-orphan')

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    description = db.Column(db.String(200))
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    note = db.Column(db.String(200))
    receipt_filename = db.Column(db.String(200))
    receipt_filepath = db.Column(db.String(300))
    
    # No relationship needed here - it's defined in Project

class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    source = db.Column(db.String(100))
    date = db.Column(db.DateTime, nullable=False)
    note = db.Column(db.Text)
    
    # No relationship needed here - it's defined in Project

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'))
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    method = db.Column(db.String(50))
    note = db.Column(db.Text)
    receipt_filename = db.Column(db.String(200))
    receipt_filepath = db.Column(db.String(300))

    worker = db.relationship('Worker', back_populates='payments')
    # No project relationship needed here - it's defined in Project

class ProjectFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    filepath = db.Column(db.String(300), nullable=False)
    category = db.Column(db.String(50))  
    note = db.Column(db.String(200))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

class WorkLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    days_worked = db.Column(db.Float)
    note = db.Column(db.Text)

    worker = db.relationship('Worker', back_populates='work_logs')
    project = db.relationship('Project', back_populates='work_logs')




class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=True)
    sms_pending_action_id = db.Column(db.Integer, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ProjectNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    note_type = db.Column(db.String(20), nullable=False)  # 'voice', 'customer', 'general'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', backref=db.backref('notes', cascade='all, delete-orphan'))


class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    is_done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    vehicle_field = db.Column(db.String(50), nullable=True)
    vehicle_offset_days = db.Column(db.Integer, nullable=True)

    user = db.relationship('User', backref=db.backref('reminders', cascade='all, delete-orphan'))


class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    vehicle_type = db.Column(db.String(20), default='Vehicle')
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.Integer)
    vin = db.Column(db.String(17))
    plate_number = db.Column(db.String(20))
    plate_expiration = db.Column(db.Date)
    registration_expiration = db.Column(db.Date)
    insurance_provider = db.Column(db.String(100))
    insurance_policy_number = db.Column(db.String(100))
    insurance_expiration = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('vehicles', cascade='all, delete-orphan'))
    reminders = db.relationship('Reminder', backref='vehicle', cascade='all, delete-orphan')


class AIActionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    channel = db.Column(db.String(20), nullable=False)  # 'web', 'sms', 'voice'
    original_msg = db.Column(db.Text, nullable=False)
    transcript = db.Column(db.Text, nullable=True)
    tool_called = db.Column(db.String(50), nullable=True)
    extracted_data = db.Column(db.Text, nullable=True)  # JSON string
    status = db.Column(db.String(20), default='pending')  # 'pending', 'confirmed', 'rejected'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    result_id = db.Column(db.Integer, nullable=True)


# ── Customer-facing sales: Customers & Quotes (Phase 1) ──

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150))
    phone = db.Column(db.String(30))
    address = db.Column(db.String(250))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    quotes = db.relationship('Quote', back_populates='customer', cascade='all, delete-orphan')


class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    # Optional link to an internal project, so an approved quote can feed cost/profit tracking.
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)

    title = db.Column(db.String(200), nullable=False)
    # draft → sent → approved / declined → converted (to invoice, Phase 2)
    status = db.Column(db.String(20), default='draft', nullable=False)
    notes = db.Column(db.Text)  # customer-facing notes shown on the PDF / approval page
    total = db.Column(db.Float, default=0.0)
    deposit = db.Column(db.Float)          # optional upfront deposit
    po_number = db.Column(db.String(50))   # optional purchase-order number

    # Secret token for the public approval link (/q/<token>) — no login required.
    public_token = db.Column(db.String(64), unique=True, nullable=False)
    public_token_expires_at = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow() + timedelta(days=30),
        nullable=False,
    )
    public_token_revoked_at = db.Column(db.DateTime)

    # E-signature capture
    signature_name = db.Column(db.String(150))
    signature_data = db.Column(db.Text)  # base64 data-URL of the drawn signature
    signed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)

    customer = db.relationship('Customer', back_populates='quotes')
    project = db.relationship('Project', backref='quotes')
    items = db.relationship('QuoteItem', back_populates='quote',
                            cascade='all, delete-orphan', order_by='QuoteItem.id')

    def recalculate_total(self):
        self.total = sum((item.line_total or 0) for item in self.items)
        return self.total


class QuoteItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, default=0.0)

    quote = db.relationship('Quote', back_populates='items')

    @property
    def line_total(self):
        return (self.quantity or 0) * (self.unit_price or 0)


# ── Customer-facing sales: Invoices (Phase 2) ──

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    # Optional links back to the internal project and the source quote.
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), nullable=True)
    # Set when this invoice bills a milestone of a contract's draw schedule (Phase 3).
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=True)

    number = db.Column(db.String(50))       # human-friendly invoice number, e.g. INV-0007
    title = db.Column(db.String(200), nullable=False)
    # draft → sent → paid  (void = cancelled)
    status = db.Column(db.String(20), default='draft', nullable=False)
    notes = db.Column(db.Text)              # customer-facing notes shown on the PDF
    total = db.Column(db.Float, default=0.0)
    deposit = db.Column(db.Float)           # deposit already collected (reduces balance due)
    po_number = db.Column(db.String(50))

    # Payment record
    paid_at = db.Column(db.DateTime)
    payment_method = db.Column(db.String(50))   # Cash / Zelle / Check / Bank transfer / Card / Other
    # If marking paid also recorded income on the linked project, we keep the id
    # so the action can be undone without leaving an orphan Income row.
    income_id = db.Column(db.Integer, db.ForeignKey('income.id'), nullable=True)

    # Public, tokenized view link (/i/<token>) — mirrors the quote approval link.
    public_token = db.Column(db.String(64), unique=True, nullable=False)
    public_token_expires_at = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow() + timedelta(days=30),
        nullable=False,
    )
    public_token_revoked_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)

    customer = db.relationship('Customer', backref='invoices')
    project = db.relationship('Project', backref='invoices')
    quote = db.relationship('Quote', backref='invoices')
    items = db.relationship('InvoiceItem', back_populates='invoice',
                            cascade='all, delete-orphan', order_by='InvoiceItem.id')

    def recalculate_total(self):
        self.total = sum((item.line_total or 0) for item in self.items)
        return self.total

    @property
    def balance_due(self):
        if self.status == 'paid':
            return 0.0
        return (self.total or 0) - (self.deposit or 0)


class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, default=0.0)

    invoice = db.relationship('Invoice', back_populates='items')

    @property
    def line_total(self):
        return (self.quantity or 0) * (self.unit_price or 0)


# ── Contracts + draw schedule / progress billing (Phase 3) ──

class Contract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), nullable=True)

    number = db.Column(db.String(50))        # e.g. CON-0003
    title = db.Column(db.String(200), nullable=False)
    contract_total = db.Column(db.Float, default=0.0)
    retainage_percent = db.Column(db.Float)  # optional % held back (informational)
    # draft → active (work under way) → completed
    status = db.Column(db.String(20), default='draft', nullable=False)
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', backref='contracts')
    project = db.relationship('Project', backref='contracts')
    quote = db.relationship('Quote', backref='contracts')
    draws = db.relationship('ContractDraw', back_populates='contract',
                            cascade='all, delete-orphan',
                            order_by='ContractDraw.sequence')

    @property
    def scheduled_total(self):
        return sum((d.amount or 0) for d in self.draws)

    @property
    def billed_to_date(self):
        return sum((d.amount or 0) for d in self.draws if d.invoice_id is not None)

    @property
    def paid_to_date(self):
        return sum((d.amount or 0) for d in self.draws if d.is_paid)

    @property
    def remaining_to_bill(self):
        return (self.contract_total or 0) - self.billed_to_date

    @property
    def retainage_amount(self):
        if not self.retainage_percent:
            return 0.0
        return (self.contract_total or 0) * (self.retainage_percent / 100.0)


class ContractDraw(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False)
    sequence = db.Column(db.Integer, default=0)
    description = db.Column(db.String(200), nullable=False)  # e.g. "Deposit", "Rough-in complete"
    amount = db.Column(db.Float, default=0.0)
    # pending → invoiced → paid (paid is derived from the linked invoice)
    status = db.Column(db.String(20), default='pending', nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)

    contract = db.relationship('Contract', back_populates='draws')
    invoice = db.relationship('Invoice', backref='contract_draw')

    @property
    def is_billed(self):
        return self.invoice_id is not None

    @property
    def is_paid(self):
        return self.invoice is not None and self.invoice.status == 'paid'
