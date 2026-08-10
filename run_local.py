# run_local.py — dev-only launcher (does not affect production / Render).
# Creates any missing tables, then serves the app on port 5001.
from app import app
from extensions import db

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(port=5001, debug=False, use_reloader=False)
