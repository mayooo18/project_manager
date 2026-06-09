from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from models import AIActionLog, Worker, Project, WorkLog, Expense, Reminder
from ai_assistant import process_message, validate_action
import json
from datetime import datetime

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')


@ai_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    body = request.get_json()
    message = body.get('message', '').strip()
    history = body.get('conversation_history', [])

    if not message:
        return jsonify({'error': 'No message provided'}), 400

    result = process_message(message, history)

    action_id = None
    validation = {'valid': True, 'errors': [], 'suggestions': []}

    if result.get('tool'):
        validation = validate_action(result['tool'], result['data'], db.session)

        log = AIActionLog(
            user_id=current_user.id,
            channel='web',
            original_msg=message,
            tool_called=result['tool'],
            extracted_data=json.dumps(result['data']),
            status='pending'
        )
        db.session.add(log)
        db.session.commit()
        action_id = log.id

    return jsonify({
        'action_id': action_id,
        'tool': result.get('tool'),
        'data': result.get('data', {}),
        'clarification_needed': result.get('clarification_needed'),
        'validation_errors': validation['errors'],
        'suggestions': validation['suggestions']
    })


@ai_bp.route('/confirm', methods=['POST'])
@login_required
def confirm():
    body = request.get_json()
    action_id = body.get('action_id')

    log = AIActionLog.query.get_or_404(action_id)
    if log.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    data = json.loads(log.extracted_data)
    tool = log.tool_called
    result_id = None

    try:
        if tool == 'create_worker':
            record = Worker(
                name=data['name'],
                daily_rate=data['daily_rate'],
                contact=data.get('contact'),
                active=data.get('active', True)
            )
            db.session.add(record)
            db.session.flush()
            result_id = record.id

        elif tool == 'create_work_log':
            worker = Worker.query.filter(
                Worker.name.ilike(data['worker_name'])
            ).first_or_404()
            project = Project.query.filter(
                Project.name.ilike(data['project_name'])
            ).first_or_404()
            record = WorkLog(
                worker_id=worker.id,
                project_id=project.id,
                days_worked=data['days_worked'],
                start_date=datetime.strptime(data['start_date'], '%Y-%m-%d').date(),
                note=data.get('note')
            )
            db.session.add(record)
            db.session.flush()
            result_id = record.id

        elif tool == 'add_expense':
            project = Project.query.filter(
                Project.name.ilike(data['project_name'])
            ).first_or_404()
            record = Expense(
                project_id=project.id,
                amount=data['amount'],
                category=data['category'],
                date=datetime.strptime(data['date'], '%Y-%m-%d'),
                description=data.get('description'),
                note=data.get('note')
            )
            db.session.add(record)
            db.session.flush()
            result_id = record.id

        elif tool == 'set_reminder':
            due = None
            if data.get('due_date'):
                due = datetime.strptime(data['due_date'], '%Y-%m-%d').date()
            record = Reminder(
                user_id=current_user.id,
                text=data['text'],
                due_date=due
            )
            db.session.add(record)
            db.session.flush()
            result_id = record.id

        elif tool == 'query_project_profit':
            project = Project.query.filter(
                Project.name.ilike(data['project_name'])
            ).first_or_404()
            total_income = sum(i.amount for i in project.incomes)
            total_expenses = sum(e.amount for e in project.expenses)
            profit = total_income - total_expenses
            log.status = 'confirmed'
            log.confirmed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'success': True,
                'message': f"{project.name}: Income ${total_income:,.2f} | Expenses ${total_expenses:,.2f} | Profit ${profit:,.2f}",
                'result_id': None
            })

        log.status = 'confirmed'
        log.confirmed_at = datetime.utcnow()
        log.result_id = result_id
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'{tool.replace("_", " ").title()} saved successfully.',
            'result_id': result_id
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_bp.route('/reject', methods=['POST'])
@login_required
def reject():
    body = request.get_json()
    action_id = body.get('action_id')

    log = AIActionLog.query.get_or_404(action_id)
    if log.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    log.status = 'rejected'
    db.session.commit()
    return jsonify({'success': True})


@ai_bp.route('/history')
@login_required
def history():
    logs = AIActionLog.query.filter_by(user_id=current_user.id)\
        .order_by(AIActionLog.created_at.desc()).limit(50).all()
    return render_template('ai_history.html', logs=logs)
