import os
import hmac
import secrets
from flask import Blueprint, request, jsonify, redirect, session, current_app
from flask_login import login_required
from functools import wraps
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import base64
import requests as http_requests
from urllib.parse import urlencode
from extensions import db
from models import Project

google_bp = Blueprint('google', __name__, url_prefix='/api/google')

SCOPES = ' '.join([
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.send'
])

REDIRECT_URI = 'https://optimalsesmanager.onrender.com/api/google/callback'


# ── Validation helper ──────────────────────────────────────────────────────
def validate_required(data, *fields):
    missing = [f for f in fields if not data.get(f)]
    if missing:
        msg = f"Missing required field(s): {', '.join(missing)}. Please provide them and try again."
        return False, (jsonify({'error': msg, 'missing_fields': missing}), 400)
    return True, None


# ── Auth helpers ───────────────────────────────────────────────────────────
def get_credentials():
    refresh_token = os.environ.get('GOOGLE_REFRESH_TOKEN')
    if not refresh_token:
        return None
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        scopes=SCOPES.split()
    )
    creds.refresh(Request())
    return creds


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        expected = os.environ.get('API_SECRET_KEY')
        key = request.headers.get('X-API-Key')
        if not expected or not key or not hmac.compare_digest(key, expected):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# ── OAuth Flow ─────────────────────────────────────────────────────────────
@google_bp.route('/auth')
@login_required
def google_auth():
    state = secrets.token_urlsafe(24)
    session['google_oauth_state'] = state
    params = urlencode({
        'client_id': os.environ.get('GOOGLE_CLIENT_ID'),
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state
    })
    return redirect(f'https://accounts.google.com/o/oauth2/auth?{params}')


@google_bp.route('/callback')
@login_required
def google_callback():
    try:
        expected_state = session.pop('google_oauth_state', None)
        state = request.args.get('state')
        if not expected_state or not hmac.compare_digest(state or '', expected_state):
            return '<h2>Error: Invalid OAuth state</h2>', 400

        code = request.args.get('code')
        if not code:
            return '<h2>Error: No code returned from Google</h2>', 400

        # Exchange code for tokens directly — no PKCE
        token_resp = http_requests.post('https://oauth2.googleapis.com/token', data={
            'code': code,
            'client_id': os.environ.get('GOOGLE_CLIENT_ID'),
            'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET'),
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code'
        })

        tokens = token_resp.json()
        refresh_token = tokens.get('refresh_token', '')

        if not refresh_token:
            return """
            <html><body style="background:#111;color:#e5e7eb;font-family:sans-serif;padding:2rem;">
            <h2 style="color:#ef4444">⚠️ No refresh token returned</h2>
            <p>Google did not return a refresh token. Try again — make sure you're prompted for consent.</p>
            <p><a href="/api/google/auth" style="color:#ff6b35">Try again</a></p>
            </body></html>
            """, 400

        return f"""
        <html><body style="background:#111;color:#e5e7eb;font-family:sans-serif;padding:2rem;">
        <h2 style="color:#ff6b35">✅ Google Connected!</h2>
        <p>Copy this refresh token and add it to Render as <strong>GOOGLE_REFRESH_TOKEN</strong>:</p>
        <textarea style="width:100%;height:100px;background:#2d2d2d;color:#4ade80;
                         border:1px solid #ff6b35;padding:0.5rem;border-radius:0.5rem;
                         font-size:0.85rem;font-family:monospace">{refresh_token}</textarea>
        <p style="color:#9ca3af;margin-top:1rem">After adding to Render → Save Changes → redeploy. Done.</p>
        </body></html>
        """
    except Exception as e:
        current_app.logger.error(f"google_callback failed: {e}", exc_info=True)
        return """
        <html><body style="background:#111;color:#e5e7eb;font-family:sans-serif;padding:2rem;">
        <h2 style="color:#ef4444">❌ Error</h2>
        <p>Something went wrong connecting to Google. Check server logs for details.</p>
        <p><a href="/api/google/auth" style="color:#ff6b35">Try again</a></p>
        </body></html>
        """, 500


# ── Google Drive ───────────────────────────────────────────────────────────
@google_bp.route('/create-folder', methods=['POST'])
@require_api_key
def create_folder():
    data = request.get_json()
    project_name = data.get('project_name')

    try:
        creds = get_credentials()
        if not creds:
            return jsonify({'error': 'Google not connected. Visit /api/google/auth first.'}), 401

        drive = build('drive', 'v3', credentials=creds)

        # Find or create root "Optimal Solutions Projects" folder
        root_name = 'Optimal Solutions Projects'
        results = drive.files().list(
            q=f"name='{root_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields='files(id, name)'
        ).execute()
        root_files = results.get('files', [])

        if root_files:
            root_id = root_files[0]['id']
        else:
            root_folder = drive.files().create(body={
                'name': root_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }, fields='id').execute()
            root_id = root_folder['id']

        # Create project folder
        project_folder = drive.files().create(body={
            'name': project_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [root_id]
        }, fields='id, name').execute()
        project_id = project_folder['id']

        # Create subfolders
        subfolders = ['Photos', 'Documents', 'Receipts', 'Voice Notes']
        for subfolder in subfolders:
            drive.files().create(body={
                'name': subfolder,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [project_id]
            }).execute()

        # Create project Google Doc
        docs = build('docs', 'v1', credentials=creds)
        doc = docs.documents().create(body={'title': f'{project_name} — Project Notes'}).execute()
        doc_id = doc['documentId']

        # Move doc into project folder
        drive.files().update(
            fileId=doc_id,
            addParents=project_id,
            removeParents='root',
            fields='id, parents'
        ).execute()

        # Save IDs back to the project in the database
        project_record = Project.query.filter(
            Project.name.ilike(f'%{project_name}%')
        ).first()
        if project_record:
            project_record.google_folder_id = project_id
            project_record.google_doc_id = doc_id
            db.session.commit()

        return jsonify({
            'message': f"Folder and doc created for {project_name}",
            'project_folder_id': project_id,
            'google_doc_id': doc_id,
            'google_doc_url': f'https://docs.google.com/document/d/{doc_id}'
        })

    except Exception as e:
        current_app.logger.error(f"create_folder failed: {e}", exc_info=True)
        return jsonify({'error': 'Internal error'}), 500


# ── Google Docs ────────────────────────────────────────────────────────────
@google_bp.route('/append-doc', methods=['POST'])
@require_api_key
def append_doc():
    data = request.get_json()
    doc_id = data.get('doc_id')
    section = data.get('section', 'Field Notes').upper()
    content = data.get('content')
    date_str = datetime.now().strftime('%m/%d/%Y %I:%M %p')

    try:
        creds = get_credentials()
        if not creds:
            return jsonify({'error': 'Google not connected. Visit /api/google/auth first.'}), 401

        docs = build('docs', 'v1', credentials=creds)
        doc = docs.documents().get(documentId=doc_id).execute()
        body_content = doc['body']['content']

        # Build full text from document
        full_text = ''
        for element in body_content:
            if 'paragraph' in element:
                for el in element['paragraph'].get('elements', []):
                    if 'textRun' in el:
                        full_text += el['textRun']['content']

        section_marker = f'═══ {section} ═══'
        new_line = f'{date_str} — {content}\n'
        section_idx = full_text.find(section_marker)

        if section_idx == -1:
            # Section doesn't exist — append heading + note at end
            end_index = body_content[-1]['endIndex'] - 1
            insert_text = f'\n\n{section_marker}\n{new_line}'
            docs.documents().batchUpdate(documentId=doc_id, body={
                'requests': [{'insertText': {'location': {'index': end_index}, 'text': insert_text}}]
            }).execute()
        else:
            # Section exists — find where to insert (before next section or at end)
            next_section_idx = full_text.find('═══', section_idx + len(section_marker))

            if next_section_idx == -1:
                # No next section — append at end of doc
                end_index = body_content[-1]['endIndex'] - 1
                docs.documents().batchUpdate(documentId=doc_id, body={
                    'requests': [{'insertText': {'location': {'index': end_index}, 'text': new_line}}]
                }).execute()
            else:
                # Find the doc index just before the next section heading
                char_pos = 0
                insert_doc_index = None
                for element in body_content:
                    if insert_doc_index:
                        break
                    if 'paragraph' in element:
                        for el in element['paragraph'].get('elements', []):
                            if 'textRun' in el:
                                text = el['textRun']['content']
                                if char_pos + len(text) >= next_section_idx - 1:
                                    offset = max(0, next_section_idx - 2 - char_pos)
                                    insert_doc_index = el['startIndex'] + offset
                                    break
                                char_pos += len(text)

                if insert_doc_index:
                    docs.documents().batchUpdate(documentId=doc_id, body={
                        'requests': [{'insertText': {'location': {'index': insert_doc_index}, 'text': new_line}}]
                    }).execute()
                else:
                    # Fallback — append at end
                    end_index = body_content[-1]['endIndex'] - 1
                    docs.documents().batchUpdate(documentId=doc_id, body={
                        'requests': [{'insertText': {'location': {'index': end_index}, 'text': new_line}}]
                    }).execute()

        return jsonify({
            'message': 'Note appended to Google Doc',
            'section': section,
            'doc_url': f'https://docs.google.com/document/d/{doc_id}'
        })

    except Exception as e:
        current_app.logger.error(f"append_doc failed: {e}", exc_info=True)
        return jsonify({'error': 'Internal error'}), 500


# ── Google Calendar ────────────────────────────────────────────────────────
@google_bp.route('/create-calendar-event', methods=['POST'])
@require_api_key
def create_calendar_event():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'title', 'date', 'time')
    if not ok:
        return err

    try:
        creds = get_credentials()
        if not creds:
            return jsonify({'error': 'Google not connected. Visit /api/google/auth first.'}), 401

        calendar = build('calendar', 'v3', credentials=creds)

        date = data.get('date')
        time = data.get('time', '08:00')
        end_time = data.get('end_time', '09:00')

        event = {
            'summary': data.get('title'),
            'description': data.get('description', ''),
            'start': {'dateTime': f"{date}T{time}:00", 'timeZone': 'America/Chicago'},
            'end': {'dateTime': f"{date}T{end_time}:00", 'timeZone': 'America/Chicago'},
            'reminders': {
                'useDefault': False,
                'overrides': [{'method': 'popup', 'minutes': 30}]
            }
        }

        created = calendar.events().insert(calendarId='primary', body=event).execute()

        return jsonify({
            'message': f"Event '{data.get('title')}' created",
            'event_url': created.get('htmlLink'),
            'event_id': created.get('id')
        })

    except Exception as e:
        current_app.logger.error(f"create_calendar_event failed: {e}", exc_info=True)
        return jsonify({'error': 'Internal error'}), 500


# ── Gmail ──────────────────────────────────────────────────────────────────
@google_bp.route('/send-email', methods=['POST'])
@require_api_key
def send_email():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'to', 'subject', 'body')
    if not ok:
        return err

    try:
        creds = get_credentials()
        if not creds:
            return jsonify({'error': 'Google not connected. Visit /api/google/auth first.'}), 401

        gmail = build('gmail', 'v1', credentials=creds)

        msg = MIMEText(data.get('body', ''))
        msg['To'] = data.get('to')
        msg['Subject'] = data.get('subject', 'Message from Optimal Solutions')
        msg['From'] = 'me'

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail.users().messages().send(userId='me', body={'raw': raw}).execute()

        return jsonify({
            'message': f"Email sent to {data.get('to')}",
            'subject': data.get('subject')
        })

    except Exception as e:
        current_app.logger.error(f"send_email failed: {e}", exc_info=True)
        return jsonify({'error': 'Internal error'}), 500
