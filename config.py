import os
from dotenv import load_dotenv
from datetime import timedelta
from urllib.parse import urlparse

load_dotenv()

class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development')
    
    DATABASE_URL = os.environ.get("DATABASE_URL")
    

    if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Local Postgres has no SSL; managed/remote (Render) requires it.
    _db_host = urlparse(DATABASE_URL).hostname if DATABASE_URL else None
    _local_db = _db_host in ('localhost', '127.0.0.1', None, '')
    

    SQLALCHEMY_ENGINE_OPTIONS = {
        
        'pool_size': 5,  
   
        'pool_recycle': 300,
        

        'pool_pre_ping': True,
        
        'pool_timeout': 20,
        
        'max_overflow': 2,
    
        'connect_args': {
 
            'sslmode': 'disable' if _local_db else 'require',
            
 
            'connect_timeout': 10,
            

            'application_name': 'project_manager',
            
            'keepalives_idle': '600',     # Send keepalive every 10 min
            'keepalives_interval': '30',   # Retry every 30 sec
            'keepalives_count': '3',       # Give up after 3 retries
        }
    }
    
    # File upload settings
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    
    # Security settings
    WTF_CSRF_ENABLED = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)
    
    # Session configuration to prevent issues
    SESSION_COOKIE_SECURE = ENVIRONMENT == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    API_SECRET_KEY = os.environ.get('API_SECRET_KEY')
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    GOOGLE_REFRESH_TOKEN = os.environ.get('GOOGLE_REFRESH_TOKEN')
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
