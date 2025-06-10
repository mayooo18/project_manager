from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
import os

app = Flask(__name__)
app.config.from_object("config.Config")

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Import models
import models

@app.route('/')
def home():
    return render_template("home.html")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
