import os
from flask import Blueprint, request, jsonify, redirect, session
from functools import wraps
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import base64
import json

google_bp = Blueprint('google', __name__, url_prefix='/api/google')

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.send'
]

CLIENT_CONFIG = {
    "web": {
        "client_id": os.environ.get('GOOGLE_CLIENT_ID'),
        "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [os.environ.get('GOOGLE_REDIRECT_URI', 'https://optimalsesmanager.onrender.com/api/google/callback')]
    }
}


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
        scopes=SCOPES
    )
    creds.refresh(Request())
    return creds


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if key != os.environ.get('API_SECRET_KEY'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# ── OAuth Flow ─────────────────────────────────────────────────────────────
@google_bp.route('/auth')
def google_auth():
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = CLIENT_CONFIG['web']['redirect_uris'][0]
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state='optimalses'
    )
    return redirect(auth_url)


@google_bp.route('/callback')
def google_callback():
    try:
        flow = Flow.from_client_config(
            CLIENT_CONFIG,
            scopes=SCOPES,
            state='optimalses'
        )
        flow.redirect_uri = CLIENT_CONFIG['web']['redirect_uris'][0]

        # Build full URL — force https for Render
        auth_response = request.url
        if auth_response.startswith('http://'):
            auth_response = auth_response.replace('http://', 'https://', 1)

        flow.fetch_token(authorization_response=auth_response)
        creds = flow.credentials
        refresh_token = creds.refresh_token

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
        return f"""
        <html><body style="background:#111;color:#e5e7eb;font-family:sans-serif;padding:2rem;">
        <h2 style="color:#ef4444">❌ Error</h2>
        <pre style="background:#2d2d2d;padding:1rem;border-radius:0.5rem;color:#fbbf24">{str(e)}</pre>
        <p><a href="/api/google/auth" style="color:#ff6b35">Try again</a></p>
        </body></html>
        """


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

        return jsonify({
            'message': f"Folder and doc created for {project_name}",
            'project_folder_id': project_id,
            'google_doc_id': doc_id,
            'google_doc_url': f'https://docs.google.com/document/d/{doc_id}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Google Docs ────────────────────────────────────────────────────────────
@google_bp.route('/append-doc', methods=['POST'])
@require_api_key
def append_doc():
    data = request.get_json()
    doc_id = data.get('doc_id')
    section = data.get('section', 'Field Notes')
    content = data.get('content')
    date_str = data.get('date', '')

    try:
        creds = get_credentials()
        if not creds:
            return jsonify({'error': 'Google not connected. Visit /api/google/auth first.'}), 401

        docs = build('docs', 'v1', credentials=creds)
        doc = docs.documents().get(documentId=doc_id).execute()
        end_index = doc['body']['content'][-1]['endIndex'] - 1

        text_to_append = f"\n\n[{section}] — {date_str}\n{content}\n"

        docs.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': [{
                'insertText': {
                    'location': {'index': end_index},
                    'text': text_to_append
                }
            }]}
        ).execute()

        return jsonify({
            'message': 'Note appended to Google Doc',
            'doc_url': f'https://docs.google.com/document/d/{doc_id}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Google Calendar ────────────────────────────────────────────────────────
@google_bp.route('/create-calendar-event', methods=['POST'])
@require_api_key
def create_calendar_event():
    data = request.get_json()

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
        return jsonify({'error': str(e)}), 500


# ── Gmail ──────────────────────────────────────────────────────────────────
@google_bp.route('/send-email', methods=['POST'])
@require_api_key
def send_email():
    data = request.get_json()

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
        return jsonify({'error': str(e)}), 500
