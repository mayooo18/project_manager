import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:

    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    WTF_CSRF_ENABLED = True

PERMANENT_SESSION_LIFETIME = timedelta(days=1)