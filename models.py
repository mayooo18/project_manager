from extensions import db
from datetime import datetime

class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(100))
    hourly_rate = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable = False)
    description = db.Column(db.Text)
    address = db.Column(db.String(200))
    start_date = db.Column(db.Date)
    status = db.Column(db.String(50), default= "Active")

    files = db.relationship("ProjectFile", backref="project",cascade="all, delete")

class ProjectFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    filepath = db.Column(db.String(300), nullable=False)
    category = db.Column(db.String(50))  
    note = db.Column(db.String(200))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

 