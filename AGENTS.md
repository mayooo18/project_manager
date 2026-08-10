# Project: Optimal Solutions Project Manager

## Stack
- Backend: Flask, Python, SQLAlchemy, PostgreSQL
- Frontend: Jinja2 HTML templates, Tailwind CSS, vanilla JavaScript
- Auth: Flask-Login
- Deployment: Render
- NO React — vanilla JS only

## Rules
- Never rewrite existing working code
- One step at a time, wait for approval
- Show all changes before applying them
- All API keys via os.environ only
- Use Flask Blueprints for new routes
- Keep new features in separate files

## Existing Files — Do Not Break
- app.py (main app, register blueprints here only)
- models.py (add to this, never remove)
- config.py (add new keys here)
- templates/base.html (add widget here carefully)

## New Files Being Added
- ai_assistant.py
- ai_routes.py
- sms_routes.py
- templates/ai_chat.html
- templates/ai_history.html
- static/js/ai_chat.js

## Environment Variables Needed
- ANTHROPIC_API_KEY
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_PHONE_NUMBER
