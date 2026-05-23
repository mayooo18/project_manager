from flask import Blueprint, request, jsonify
from functools import wraps
from datetime import datetime, date, timedelta
import os
from extensions import db
from models import Worker, Project, WorkLog, Expense, Income, ProjectFile, ProjectNote

api_bp = Blueprint('api', __name__, url_prefix='/api')


# ── Validation helpers ─────────────────────────────────────────────────────
def validate_required(data, *fields):
    """Return (True, None) if all fields present, else (False, error response)."""
    missing = [f for f in fields if not data.get(f)]
    if missing:
        msg = f"Missing required field(s): {', '.join(missing)}. Please provide them and try again."
        return False, (jsonify({'error': msg, 'missing_fields': missing}), 400)
    return True, None


def find_worker(name):
    """Fuzzy-find a worker; return (worker, None) or (None, error response)."""
    worker = Worker.query.filter(Worker.name.ilike(f"%{name}%")).first()
    if not worker:
        available = [w.name for w in Worker.query.filter_by(active=True).all()]
        msg = f"Worker '{name}' not found. Available workers: {', '.join(available) or 'none yet'}."
        return None, (jsonify({'error': msg, 'available_workers': available}), 404)
    return worker, None


def find_project(name):
    """Fuzzy-find a project; return (project, None) or (None, error response)."""
    project = Project.query.filter(Project.name.ilike(f"%{name}%")).first()
    if not project:
        available = [p.name for p in Project.query.filter_by(status='Active').all()]
        msg = f"Project '{name}' not found. Active projects: {', '.join(available) or 'none yet'}."
        return None, (jsonify({'error': msg, 'available_projects': available}), 404)
    return project, None


# ── Auth ───────────────────────────────────────────────────────────────────
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if key != os.environ.get('API_SECRET_KEY'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# ── Projects ───────────────────────────────────────────────────────────────
@api_bp.route('/projects', methods=['GET'])
@require_api_key
def list_projects():
    projects = Project.query.all()
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'status': p.status,
        'address': p.address,
        'description': p.description
    } for p in projects])


@api_bp.route('/projects', methods=['POST'])
@require_api_key
def create_project():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'name')
    if not ok:
        return err
    project = Project(
        name=data['name'],
        description=data.get('description'),
        address=data.get('address'),
        start_date=datetime.strptime(data['start_date'], '%Y-%m-%d').date() if data.get('start_date') else date.today(),
        status=data.get('status', 'Active')
    )
    db.session.add(project)
    db.session.commit()
    return jsonify({
        'id': project.id,
        'name': project.name,
        'message': 'Project created',
        'drive_folder': f'Optimal Solutions Projects/{project.name}',
        'drive_subfolders': ['Photos', 'Documents', 'Receipts']
    }), 201


@api_bp.route('/projects/<int:project_id>/summary', methods=['GET'])
@require_api_key
def project_summary(project_id):
    p = Project.query.get_or_404(project_id)
    total_income = sum(i.amount for i in p.incomes)
    total_expenses = sum(e.amount for e in p.expenses)
    labor_cost = sum((l.hours_worked or 0) * l.worker.hourly_rate for l in p.work_logs)
    total_hours = sum(l.hours_worked or 0 for l in p.work_logs)
    notes = ProjectNote.query.filter_by(project_id=project_id)\
        .order_by(ProjectNote.created_at.desc()).limit(5).all()
    return jsonify({
        'id': p.id,
        'name': p.name,
        'status': p.status,
        'address': p.address,
        'description': p.description,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'labor_cost': round(labor_cost, 2),
        'profit': round(total_income - total_expenses - labor_cost, 2),
        'total_hours': total_hours,
        'recent_notes': [{
            'type': n.note_type,
            'content': n.content,
            'date': n.created_at.strftime('%Y-%m-%d %I:%M %p')
        } for n in notes]
    })


@api_bp.route('/projects/<int:project_id>/status', methods=['PATCH'])
@require_api_key
def update_project_status(project_id):
    p = Project.query.get_or_404(project_id)
    data = request.get_json()
    p.status = data['status']
    db.session.commit()
    return jsonify({'message': f"Project status updated to {p.status}"})


@api_bp.route('/projects/<int:project_id>', methods=['DELETE'])
@require_api_key
def delete_project_api(project_id):
    p = Project.query.get_or_404(project_id)
    db.session.delete(p)
    db.session.commit()
    return jsonify({'message': f"Project '{p.name}' deleted"})


# ── Workers ────────────────────────────────────────────────────────────────
@api_bp.route('/workers', methods=['GET'])
@require_api_key
def list_workers():
    workers = Worker.query.filter_by(active=True).all()
    return jsonify([{
        'id': w.id,
        'name': w.name,
        'hourly_rate': w.hourly_rate,
        'contact': w.contact
    } for w in workers])


@api_bp.route('/workers', methods=['POST'])
@require_api_key
def create_worker_api():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'name', 'hourly_rate')
    if not ok:
        return err
    worker = Worker(
        name=data['name'],
        hourly_rate=data['hourly_rate'],
        contact=data.get('contact'),
        active=data.get('active', True)
    )
    db.session.add(worker)
    db.session.commit()
    return jsonify({'id': worker.id, 'name': worker.name, 'message': 'Worker created'}), 201


@api_bp.route('/workers/<int:worker_id>', methods=['PATCH'])
@require_api_key
def update_worker_api(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    data = request.get_json()
    if 'hourly_rate' in data:
        worker.hourly_rate = data['hourly_rate']
    if 'contact' in data:
        worker.contact = data['contact']
    if 'active' in data:
        worker.active = data['active']
    db.session.commit()
    return jsonify({'message': f"Worker '{worker.name}' updated"})


@api_bp.route('/workers/<int:worker_id>', methods=['DELETE'])
@require_api_key
def delete_worker_api(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    db.session.delete(worker)
    db.session.commit()
    return jsonify({'message': f"Worker '{worker.name}' deleted"})


@api_bp.route('/workers/<int:worker_id>/logs', methods=['GET'])
@require_api_key
def worker_logs(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    days = request.args.get('days', 7, type=int)
    since = date.today() - timedelta(days=days)
    logs = WorkLog.query.filter(
        WorkLog.worker_id == worker_id,
        WorkLog.start_date >= since
    ).all()
    total_hours = sum(l.hours_worked or 0 for l in logs)
    return jsonify({
        'worker': worker.name,
        'hourly_rate': worker.hourly_rate,
        'period_days': days,
        'total_hours': total_hours,
        'total_pay': round(total_hours * worker.hourly_rate, 2),
        'logs': [{
            'project': l.project.name,
            'date': str(l.start_date),
            'hours': l.hours_worked,
            'note': l.note
        } for l in logs]
    })


# ── Field Capture ──────────────────────────────────────────────────────────
@api_bp.route('/field/voice-note', methods=['POST'])
@require_api_key
def voice_note():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'project_name', 'content')
    if not ok:
        return err
    project, err = find_project(data['project_name'])
    if err:
        return err
    note = ProjectNote(
        project_id=project.id,
        note_type='voice',
        content=data['content']
    )
    db.session.add(note)
    db.session.commit()
    return jsonify({
        'message': 'Voice note saved',
        'project': project.name,
        'note_id': note.id,
        'google_doc_append': {
            'project_name': project.name,
            'section': 'Field Notes',
            'date': datetime.utcnow().strftime('%Y-%m-%d %I:%M %p'),
            'content': data['content']
        }
    })


@api_bp.route('/field/work-log', methods=['POST'])
@require_api_key
def field_work_log():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'worker_name', 'project_name', 'hours_worked', 'date')
    if not ok:
        return err
    worker, err = find_worker(data['worker_name'])
    if err:
        return err
    project, err = find_project(data['project_name'])
    if err:
        return err
    log = WorkLog(
        worker_id=worker.id,
        project_id=project.id,
        hours_worked=data['hours_worked'],
        start_date=datetime.strptime(data['date'], '%Y-%m-%d').date() if data.get('date') else date.today(),
        note=data.get('note')
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({
        'message': f"Logged {data['hours_worked']} hrs for {worker.name} on {project.name}",
        'log_id': log.id
    })


@api_bp.route('/field/expense', methods=['POST'])
@require_api_key
def field_expense():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'project_name', 'amount', 'category', 'date')
    if not ok:
        return err
    project, err = find_project(data['project_name'])
    if err:
        return err
    expense = Expense(
        project_id=project.id,
        amount=data['amount'],
        category=data['category'],
        date=datetime.strptime(data['date'], '%Y-%m-%d') if data.get('date') else datetime.utcnow(),
        description=data.get('description'),
        note=data.get('note')
    )
    db.session.add(expense)
    db.session.commit()
    return jsonify({
        'message': f"${data['amount']} expense logged for {project.name}",
        'expense_id': expense.id
    })


@api_bp.route('/field/photo', methods=['POST'])
@require_api_key
def field_photo():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'project_name', 'filename')
    if not ok:
        return err
    project, err = find_project(data['project_name'])
    if err:
        return err
    file_record = ProjectFile(
        project_id=project.id,
        filename=data['filename'],
        filepath=data.get('drive_url', ''),
        category=data.get('category', 'photo'),
        note=data.get('note')
    )
    db.session.add(file_record)
    db.session.commit()
    return jsonify({
        'message': 'Photo logged to dashboard',
        'file_id': file_record.id,
        'drive_path': f"Optimal Solutions Projects/{project.name}/Photos/{data.get('category', 'General')}"
    })


@api_bp.route('/field/customer-note', methods=['POST'])
@require_api_key
def customer_note():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'project_name', 'content')
    if not ok:
        return err
    project, err = find_project(data['project_name'])
    if err:
        return err
    note = ProjectNote(
        project_id=project.id,
        note_type='customer',
        content=data['content']
    )
    db.session.add(note)
    db.session.commit()
    return jsonify({
        'message': 'Customer note saved',
        'project': project.name,
        'note_id': note.id,
        'google_doc_append': {
            'project_name': project.name,
            'section': 'Customer Notes',
            'date': datetime.utcnow().strftime('%Y-%m-%d %I:%M %p'),
            'content': data['content']
        }
    })


@api_bp.route('/field/reminder', methods=['POST'])
@require_api_key
def create_reminder():
    data = request.get_json() or {}
    ok, err = validate_required(data, 'title', 'date', 'time')
    if not ok:
        return err
    return jsonify({
        'message': 'Reminder ready for Google Calendar',
        'calendar_event': {
            'title': data['title'],
            'date': data['date'],
            'time': data.get('time', '08:00'),
            'description': data.get('description', ''),
            'project': data.get('project_name', '')
        }
    })


@api_bp.route('/field/today', methods=['GET'])
@require_api_key
def today_briefing():
    today = date.today()
    logs = WorkLog.query.filter(WorkLog.start_date == today).all()
    summary = {}
    for log in logs:
        name = log.project.name
        if name not in summary:
            summary[name] = []
        summary[name].append({
            'worker': log.worker.name,
            'hours': log.hours_worked,
            'note': log.note
        })
    active_projects = Project.query.filter_by(status='Active').count()
    return jsonify({
        'date': str(today),
        'active_projects': active_projects,
        'projects_with_logs_today': list(summary.keys()),
        'details': summary,
        'total_workers_today': len(logs)
    })


# ── Reports ────────────────────────────────────────────────────────────────
@api_bp.route('/reports/payroll', methods=['GET'])
@require_api_key
def payroll_report():
    days = request.args.get('days', 7, type=int)
    since = date.today() - timedelta(days=days)
    workers = Worker.query.filter_by(active=True).all()
    report = []
    for worker in workers:
        logs = WorkLog.query.filter(
            WorkLog.worker_id == worker.id,
            WorkLog.start_date >= since
        ).all()
        total_hours = sum(l.hours_worked or 0 for l in logs)
        if total_hours > 0:
            report.append({
                'worker': worker.name,
                'hourly_rate': worker.hourly_rate,
                'total_hours': total_hours,
                'total_pay': round(total_hours * worker.hourly_rate, 2)
            })
    return jsonify({
        'period_days': days,
        'since': str(since),
        'workers': report,
        'total_payroll': round(sum(r['total_pay'] for r in report), 2)
    })


@api_bp.route('/reports/project-profit/<int:project_id>', methods=['GET'])
@require_api_key
def project_profit(project_id):
    p = Project.query.get_or_404(project_id)
    total_income = sum(i.amount for i in p.incomes)
    total_expenses = sum(e.amount for e in p.expenses)
    labor_cost = sum((l.hours_worked or 0) * l.worker.hourly_rate for l in p.work_logs)
    return jsonify({
        'project': p.name,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'labor_cost': round(labor_cost, 2),
        'total_cost': round(total_expenses + labor_cost, 2),
        'profit': round(total_income - total_expenses - labor_cost, 2)
    })


# ── Recent Entries & Delete ────────────────────────────────────────────────
@api_bp.route('/field/recent', methods=['GET'])
@require_api_key
def recent_entries():
    limit = request.args.get('limit', 100, type=int)
    entry_type = request.args.get('type')       # 'work-log', 'expense', 'note'
    project_name = request.args.get('project')  # partial match

    entries = []

    if not entry_type or entry_type == 'work-log':
        q = WorkLog.query
        if project_name:
            q = q.join(Project).filter(Project.name.ilike(f'%{project_name}%'))
        logs = q.order_by(WorkLog.id.desc()).limit(limit).all()
        for l in logs:
            entries.append({
                'type': 'work-log',
                'id': l.id,
                'worker': l.worker.name,
                'project': l.project.name,
                'hours': l.hours_worked,
                'date': str(l.start_date),
                'note': l.note
            })

    if not entry_type or entry_type == 'expense':
        q = Expense.query
        if project_name:
            q = q.join(Project).filter(Project.name.ilike(f'%{project_name}%'))
        expenses = q.order_by(Expense.id.desc()).limit(limit).all()
        for e in expenses:
            entries.append({
                'type': 'expense',
                'id': e.id,
                'project': e.project.name,
                'amount': e.amount,
                'category': e.category,
                'date': e.date.strftime('%Y-%m-%d'),
                'description': e.description,
                'note': e.note
            })

    if not entry_type or entry_type == 'note':
        q = ProjectNote.query
        if project_name:
            q = q.join(Project).filter(Project.name.ilike(f'%{project_name}%'))
        notes = q.order_by(ProjectNote.id.desc()).limit(limit).all()
        for n in notes:
            entries.append({
                'type': 'note',
                'id': n.id,
                'note_type': n.note_type,
                'project': n.project.name,
                'content': n.content,
                'date': n.created_at.strftime('%Y-%m-%d %I:%M %p')
            })

    # Sort all combined results by id descending (most recent first)
    entries.sort(key=lambda x: x['id'], reverse=True)

    return jsonify({
        'count': len(entries),
        'entries': entries[:limit]
    })


@api_bp.route('/field/work-log/<int:log_id>', methods=['DELETE'])
@require_api_key
def delete_work_log(log_id):
    log = WorkLog.query.get_or_404(log_id)
    summary = f"{log.hours_worked} hrs for {log.worker.name} on {log.project.name} ({log.start_date})"
    db.session.delete(log)
    db.session.commit()
    return jsonify({'message': f"Deleted: {summary}"})


@api_bp.route('/field/expense/<int:expense_id>', methods=['DELETE'])
@require_api_key
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    summary = f"${expense.amount} {expense.category} on {expense.project.name} ({expense.date.strftime('%Y-%m-%d')})"
    db.session.delete(expense)
    db.session.commit()
    return jsonify({'message': f"Deleted: {summary}"})


@api_bp.route('/field/note/<int:note_id>', methods=['DELETE'])
@require_api_key
def delete_note(note_id):
    note = ProjectNote.query.get_or_404(note_id)
    summary = f"{note.note_type} note on {note.project.name}: \"{note.content[:60]}...\""
    db.session.delete(note)
    db.session.commit()
    return jsonify({'message': f"Deleted: {summary}"})


# ── OpenAPI Spec ───────────────────────────────────────────────────────────
@api_bp.route('/openapi.json', methods=['GET'])
def openapi_spec():
    base_url = request.host_url.rstrip('/')
    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "Optimal Solutions Field API",
            "description": "Construction business API for Optimal Solutions. Use this to log workers, projects, expenses, work hours, voice notes, and photos from the field.",
            "version": "1.0.0"
        },
        "servers": [{"url": base_url}],
        "components": {
            "schemas": {}
        },
        "paths": {
            "/api/projects": {
                "get": {
                    "operationId": "listProjects",
                    "summary": "List all projects",
                    "responses": {"200": {"description": "List of projects"}}
                },
                "post": {
                    "operationId": "createProject",
                    "summary": "Create a new project",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "address": {"type": "string"},
                                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                                "status": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"201": {"description": "Project created"}}
                }
            },
            "/api/projects/{project_id}/summary": {
                "get": {
                    "operationId": "getProjectSummary",
                    "summary": "Get full project summary including profit, hours, and recent notes",
                    "parameters": [{"name": "project_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "Project summary"}}
                }
            },
            "/api/projects/{project_id}/status": {
                "patch": {
                    "operationId": "updateProjectStatus",
                    "summary": "Update project status (Active, Completed, On Hold)",
                    "parameters": [{"name": "project_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["status"],
                            "properties": {"status": {"type": "string"}}
                        }}}
                    },
                    "responses": {"200": {"description": "Status updated"}}
                }
            },
            "/api/projects/{project_id}": {
                "delete": {
                    "operationId": "deleteProject",
                    "summary": "Delete a project",
                    "parameters": [{"name": "project_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "Project deleted"}}
                }
            },
            "/api/workers": {
                "get": {
                    "operationId": "listWorkers",
                    "summary": "List all active workers",
                    "responses": {"200": {"description": "List of workers"}}
                },
                "post": {
                    "operationId": "createWorker",
                    "summary": "Add a new worker",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["name", "hourly_rate"],
                            "properties": {
                                "name": {"type": "string"},
                                "hourly_rate": {"type": "number"},
                                "contact": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"201": {"description": "Worker created"}}
                }
            },
            "/api/workers/{worker_id}": {
                "patch": {
                    "operationId": "updateWorker",
                    "summary": "Update worker hourly rate or contact info",
                    "parameters": [{"name": "worker_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "hourly_rate": {"type": "number"},
                                "contact": {"type": "string"},
                                "active": {"type": "boolean"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Worker updated"}}
                },
                "delete": {
                    "operationId": "deleteWorker",
                    "summary": "Delete a worker",
                    "parameters": [{"name": "worker_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "Worker deleted"}}
                }
            },
            "/api/workers/{worker_id}/logs": {
                "get": {
                    "operationId": "getWorkerLogs",
                    "summary": "Get hours and pay for a worker over the last N days",
                    "parameters": [
                        {"name": "worker_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                        {"name": "days", "in": "query", "schema": {"type": "integer", "default": 7}}
                    ],
                    "responses": {"200": {"description": "Worker log summary"}}
                }
            },
            "/api/field/voice-note": {
                "post": {
                    "operationId": "addVoiceNote",
                    "summary": "Save a transcribed voice note to a project",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["project_name", "content"],
                            "properties": {
                                "project_name": {"type": "string"},
                                "content": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Note saved"}}
                }
            },
            "/api/field/work-log": {
                "post": {
                    "operationId": "logWorkHours",
                    "summary": "Log hours worked by a worker on a project",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["worker_name", "project_name", "hours_worked"],
                            "properties": {
                                "worker_name": {"type": "string"},
                                "project_name": {"type": "string"},
                                "hours_worked": {"type": "number"},
                                "date": {"type": "string", "description": "YYYY-MM-DD"},
                                "note": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Hours logged"}}
                }
            },
            "/api/field/expense": {
                "post": {
                    "operationId": "logExpense",
                    "summary": "Log an expense for a project",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["project_name", "amount", "category"],
                            "properties": {
                                "project_name": {"type": "string"},
                                "amount": {"type": "number"},
                                "category": {"type": "string"},
                                "date": {"type": "string"},
                                "description": {"type": "string"},
                                "note": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Expense logged"}}
                }
            },
            "/api/field/photo": {
                "post": {
                    "operationId": "logPhoto",
                    "summary": "Log a photo to a project. Returns the Drive folder path where GPT should upload the file.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["project_name", "filename"],
                            "properties": {
                                "project_name": {"type": "string"},
                                "filename": {"type": "string"},
                                "category": {"type": "string", "description": "e.g. Before, After, Repairs Not Seen"},
                                "drive_url": {"type": "string"},
                                "note": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Photo logged"}}
                }
            },
            "/api/field/customer-note": {
                "post": {
                    "operationId": "addCustomerNote",
                    "summary": "Log a customer request, complaint, or conversation note",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["project_name", "content"],
                            "properties": {
                                "project_name": {"type": "string"},
                                "content": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Customer note saved"}}
                }
            },
            "/api/field/reminder": {
                "post": {
                    "operationId": "createReminder",
                    "summary": "Create a reminder. Returns calendar event details for GPT to add to Google Calendar.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["title", "date"],
                            "properties": {
                                "title": {"type": "string"},
                                "date": {"type": "string", "description": "YYYY-MM-DD"},
                                "time": {"type": "string", "description": "HH:MM"},
                                "description": {"type": "string"},
                                "project_name": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Reminder details returned"}}
                }
            },
            "/api/field/today": {
                "get": {
                    "operationId": "getTodayBriefing",
                    "summary": "Get today's work summary — who is working where",
                    "responses": {"200": {"description": "Today's briefing"}}
                }
            },
            "/api/field/recent": {
                "get": {
                    "operationId": "getRecentEntries",
                    "summary": "Get up to 100 recent work logs, expenses, and notes with their IDs. Use this before deleting to find the right entry.",
                    "parameters": [
                        {"name": "type", "in": "query", "schema": {"type": "string", "enum": ["work-log", "expense", "note"]}, "description": "Filter by entry type"},
                        {"name": "project", "in": "query", "schema": {"type": "string"}, "description": "Filter by project name (partial match)"},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}}
                    ],
                    "responses": {"200": {"description": "List of recent entries with IDs"}}
                }
            },
            "/api/field/work-log/{log_id}": {
                "delete": {
                    "operationId": "deleteWorkLog",
                    "summary": "Delete a work log entry by ID. Always confirm with the user before calling this.",
                    "parameters": [{"name": "log_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "Work log deleted"}}
                }
            },
            "/api/field/expense/{expense_id}": {
                "delete": {
                    "operationId": "deleteExpense",
                    "summary": "Delete an expense entry by ID. Always confirm with the user before calling this.",
                    "parameters": [{"name": "expense_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "Expense deleted"}}
                }
            },
            "/api/field/note/{note_id}": {
                "delete": {
                    "operationId": "deleteNote",
                    "summary": "Delete a project note by ID. Always confirm with the user before calling this.",
                    "parameters": [{"name": "note_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "Note deleted"}}
                }
            },
            "/api/reports/payroll": {
                "get": {
                    "operationId": "getPayrollReport",
                    "summary": "Get payroll report — hours and pay owed per worker",
                    "parameters": [
                        {"name": "days", "in": "query", "schema": {"type": "integer", "default": 7}}
                    ],
                    "responses": {"200": {"description": "Payroll report"}}
                }
            },
            "/api/reports/project-profit/{project_id}": {
                "get": {
                    "operationId": "getProjectProfit",
                    "summary": "Get income vs expenses vs labor cost for a project",
                    "parameters": [{"name": "project_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "Project profit report"}}
                }
            },
            "/api/google/create-folder": {
                "post": {
                    "operationId": "createGoogleFolder",
                    "summary": "Create a Google Drive project folder with subfolders (Photos, Documents, Receipts, Voice Notes) and a linked Google Doc for notes",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["project_name"],
                            "properties": {
                                "project_name": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Folder and doc created, returns google_doc_id and folder_id"}}
                }
            },
            "/api/google/append-doc": {
                "post": {
                    "operationId": "appendToGoogleDoc",
                    "summary": "Append a voice note or customer note to a project's Google Doc",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["doc_id", "content"],
                            "properties": {
                                "doc_id": {"type": "string", "description": "Google Doc ID"},
                                "section": {"type": "string", "description": "e.g. Field Notes, Customer Notes"},
                                "content": {"type": "string"},
                                "date": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Note appended to doc"}}
                }
            },
            "/api/google/create-calendar-event": {
                "post": {
                    "operationId": "createCalendarEvent",
                    "summary": "Create a Google Calendar event or reminder",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["title", "date"],
                            "properties": {
                                "title": {"type": "string"},
                                "date": {"type": "string", "description": "YYYY-MM-DD"},
                                "time": {"type": "string", "description": "HH:MM, default 08:00"},
                                "end_time": {"type": "string", "description": "HH:MM, default 09:00"},
                                "description": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Calendar event created"}}
                }
            },
            "/api/google/send-email": {
                "post": {
                    "operationId": "sendEmail",
                    "summary": "Send an email from Mario's Gmail account",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["to", "subject", "body"],
                            "properties": {
                                "to": {"type": "string", "description": "Recipient email address"},
                                "subject": {"type": "string"},
                                "body": {"type": "string"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Email sent"}}
                }
            }
        }
    }
    return jsonify(spec)
