from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from models import (
    AIActionLog, Worker, Project, WorkLog, Expense, Reminder,
    Customer, Invoice, Quote, QuoteItem,
)
from ai_assistant import process_message, validate_action
from quote_routes import _new_token
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
                phone=Worker.normalize_phone(data.get('phone')),
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

        elif tool == 'create_customer':
            record = Customer(
                user_id=current_user.id,
                name=data['name'],
                email=data.get('email'),
                phone=data.get('phone'),
                address=data.get('address'),
            )
            db.session.add(record)
            db.session.flush()
            result_id = record.id

        elif tool == 'draft_proposal':
            customer = Customer.query.filter(
                Customer.user_id == current_user.id,
                Customer.name.ilike(data['customer_name'])
            ).first_or_404()
            quote = Quote(
                user_id=current_user.id,
                customer_id=customer.id,
                title=data['title'],
                status='draft',
                public_token=_new_token(),
            )
            db.session.add(quote)
            if data.get('description') or data.get('amount'):
                quote.items.append(QuoteItem(
                    description=data.get('description') or data['title'],
                    quantity=1,
                    unit_price=data.get('amount') or 0,
                ))
                quote.recalculate_total()
            db.session.flush()
            result_id = quote.id

        elif tool == 'query_invoice_status':
            inv = Invoice.query.filter(
                Invoice.user_id == current_user.id,
                Invoice.number.ilike(data['invoice_number'])
            ).first()
            log.status = 'confirmed'
            log.confirmed_at = datetime.utcnow()
            db.session.commit()
            if not inv:
                return jsonify({'success': True, 'result_id': None,
                                'message': f"No invoice found matching '{data['invoice_number']}'."})
            extra = ''
            if inv.status == 'paid' and inv.paid_at:
                extra = f" · paid {inv.paid_at.strftime('%Y-%m-%d')}" + (
                    f" via {inv.payment_method}" if inv.payment_method else '')
            return jsonify({'success': True, 'result_id': None,
                            'message': f"{inv.number}: {inv.title} — ${inv.total:,.2f} — {inv.status.upper()}{extra}"})

        elif tool == 'query_job_summary':
            project = Project.query.filter(
                Project.name.ilike(data['project_name'])
            ).first_or_404()
            contracts = list(project.contracts)
            contract_total = sum(c.contract_total or 0 for c in contracts)
            billed = sum(c.billed_to_date for c in contracts)
            paid = sum(i.total or 0 for i in project.invoices if i.status == 'paid')
            profit = (sum(i.amount or 0 for i in project.incomes)
                      - sum(e.amount or 0 for e in project.expenses)
                      - sum(p.amount or 0 for p in project.payments))
            log.status = 'confirmed'
            log.confirmed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True, 'result_id': None,
                            'message': f"{project.name} [{project.status}]: Contract ${contract_total:,.0f} · "
                                       f"Billed ${billed:,.0f} · Paid ${paid:,.0f} · Profit ${profit:,.0f}"})

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
