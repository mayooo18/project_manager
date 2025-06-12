from extensions import db

class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(100))
    hourly_rate = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)
