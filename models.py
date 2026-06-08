from extensions import db
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    contact = db.Column(db.String(100))
    hourly_rate = db.Column(db.Float)
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
    hours_worked = db.Column(db.Float)
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

    user = db.relationship('User', backref=db.backref('reminders', cascade='all, delete-orphan'))


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