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
    # Client portal magic-link (Phase 5): one private, revocable link per job.
    portal_token = db.Column(db.String(64), unique=True, nullable=True)
    portal_token_revoked_at = db.Column(db.DateTime, nullable=True)
    # Customer + Location links (Phase 7): who the job is for, and which property.
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True)
    customer = db.relationship('Customer', backref='projects')
    location = db.relationship('Location', backref='projects')

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
    # Set when this payment was auto-generated from a work log (Phase 7 §5a).
    work_log_id = db.Column(db.Integer, db.ForeignKey('work_log.id'), nullable=True)

    worker = db.relationship('Worker', back_populates='payments')
    work_log = db.relationship('WorkLog', backref=db.backref('payment', uselist=False))
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
    # Same auto-reminder mechanism, reused for subcontractor license/insurance expirations.
    subcontractor_id = db.Column(db.Integer, db.ForeignKey('subcontractor.id'), nullable=True)
    subcontractor_field = db.Column(db.String(50), nullable=True)
    subcontractor_offset_days = db.Column(db.Integer, nullable=True)
    # Same auto-reminder mechanism, reused for the company's own license/credential renewals.
    license_id = db.Column(db.Integer, db.ForeignKey('license.id'), nullable=True)
    license_field = db.Column(db.String(50), nullable=True)
    license_offset_days = db.Column(db.Integer, nullable=True)
    # Permit expiration + inspection scheduled-date reminders (Phase 6c).
    permit_id = db.Column(db.Integer, db.ForeignKey('permit.id'), nullable=True)
    permit_field = db.Column(db.String(50), nullable=True)
    permit_offset_days = db.Column(db.Integer, nullable=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey('inspection.id'), nullable=True)
    inspection_field = db.Column(db.String(50), nullable=True)
    inspection_offset_days = db.Column(db.Integer, nullable=True)

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


class Subcontractor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)   # company or person
    trade = db.Column(db.String(80))                   # Electrical, Plumbing, HVAC, Framing...
    contact_name = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(150))
    license_number = db.Column(db.String(80))
    license_expiration = db.Column(db.Date)
    insurance_carrier = db.Column(db.String(120))
    insurance_policy_number = db.Column(db.String(80))
    insurance_expiration = db.Column(db.Date)
    w9_on_file = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('subcontractors', cascade='all, delete-orphan'))
    reminders = db.relationship('Reminder', backref='subcontractor', cascade='all, delete-orphan')


class License(db.Model):
    """The company's own credentials (electrical/HVAC/GC licenses, bonds, insurance)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)   # e.g. "IL Electrical Contractor License"
    credential_type = db.Column(db.String(40), default='License')  # License / Insurance / Bond / Certification
    number = db.Column(db.String(80))
    issuer = db.Column(db.String(120))                 # state, municipality, carrier, surety
    issued_date = db.Column(db.Date)
    expiration_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('licenses', cascade='all, delete-orphan'))
    reminders = db.relationship('Reminder', backref='license', cascade='all, delete-orphan')


class Permit(db.Model):
    """A building/trade permit pulled for a project (Phase 6c)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    permit_type = db.Column(db.String(80))      # Building / Electrical / Plumbing / Mechanical (HVAC)...
    permit_number = db.Column(db.String(80))
    issuing_authority = db.Column(db.String(120))  # city / county / village
    status = db.Column(db.String(30), default='Applied')  # Applied / Issued / Expired / Finaled / Closed
    applied_date = db.Column(db.Date)
    issued_date = db.Column(db.Date)
    expiration_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('permits', cascade='all, delete-orphan'))
    project = db.relationship('Project', backref='permits')
    inspections = db.relationship('Inspection', back_populates='permit',
                                  cascade='all, delete-orphan',
                                  order_by='Inspection.scheduled_date')
    reminders = db.relationship('Reminder', backref='permit', cascade='all, delete-orphan')


class Inspection(db.Model):
    """An inspection under a permit (Phase 6c)."""
    id = db.Column(db.Integer, primary_key=True)
    permit_id = db.Column(db.Integer, db.ForeignKey('permit.id'), nullable=False)
    inspection_type = db.Column(db.String(80), nullable=False)  # Footing / Framing / Rough Electrical / Final...
    scheduled_date = db.Column(db.Date)
    status = db.Column(db.String(30), default='Scheduled')  # Scheduled / Passed / Failed / Cancelled
    result_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    permit = db.relationship('Permit', back_populates='inspections')
    reminders = db.relationship('Reminder', backref='inspection', cascade='all, delete-orphan')


class GcDocument(db.Model):
    """Lien waivers + certificates of completion (Phase 6d). PDF-generated records."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # conditional_progress / unconditional_progress / conditional_final /
    # unconditional_final / completion
    doc_kind = db.Column(db.String(40), nullable=False, default='conditional_progress')
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)

    owner_name = db.Column(db.String(150))
    property_address = db.Column(db.String(250))
    amount = db.Column(db.Float)               # payment amount (waivers)
    through_date = db.Column(db.Date)          # "through" date (progress) or completion date
    check_number = db.Column(db.String(60))
    exceptions = db.Column(db.Text)            # disputed/excluded amounts
    notes = db.Column(db.Text)                 # scope of work for completion certs
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('gc_documents', cascade='all, delete-orphan'))
    project = db.relationship('Project', backref='gc_documents')
    customer = db.relationship('Customer', backref='gc_documents')


def find_or_create_location(user_id, customer_id, address):
    """Return the customer's Location for this address (reused if it already
    exists, case/space-insensitive), creating one if needed. None if no
    customer or address. Flushes so the caller gets an id."""
    addr = (address or '').strip()
    if not customer_id or not addr:
        return None
    norm = ' '.join(addr.lower().split())
    for loc in Location.query.filter_by(customer_id=customer_id).all():
        if ' '.join((loc.address or '').strip().lower().split()) == norm:
            return loc
    loc = Location(user_id=user_id, customer_id=customer_id, label=addr[:150], address=addr)
    db.session.add(loc)
    db.session.flush()
    return loc


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


class Location(db.Model):
    """A property/address belonging to a customer (Phase 7). A customer can have
    many locations; a location can have many jobs over time (repeat work)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    label = db.Column(db.String(150))     # short name, defaults to the address
    address = db.Column(db.String(250))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', backref=db.backref('locations', cascade='all, delete-orphan'))


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


# ── Change Orders (Phase 4) ──

class ChangeOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)

    number = db.Column(db.String(50))
    title = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='draft', nullable=False)
    total = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text)
    add_as_draw = db.Column(db.Boolean, default=True)

    # Snapshots prove exactly how an approved amendment changed the contract.
    applied_at = db.Column(db.DateTime)
    contract_total_before = db.Column(db.Float)
    contract_total_after = db.Column(db.Float)

    public_token = db.Column(db.String(64), unique=True, nullable=False)
    public_token_expires_at = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow() + timedelta(days=30),
        nullable=False,
    )
    public_token_revoked_at = db.Column(db.DateTime)

    signature_name = db.Column(db.String(150))
    signature_data = db.Column(db.Text)
    signed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)

    contract = db.relationship('Contract', backref='change_orders')
    customer = db.relationship('Customer')
    items = db.relationship(
        'ChangeOrderItem', back_populates='change_order',
        cascade='all, delete-orphan', order_by='ChangeOrderItem.id')

    def recalculate_total(self):
        self.total = sum((item.line_total or 0) for item in self.items)
        return self.total


class ChangeOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    change_order_id = db.Column(
        db.Integer, db.ForeignKey('change_order.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, default=0.0)

    change_order = db.relationship('ChangeOrder', back_populates='items')

    @property
    def line_total(self):
        return (self.quantity or 0) * (self.unit_price or 0)
