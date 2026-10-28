"""Weekly progress reports (F11).

A per-customer weekly report, auto-built from existing data (each property's
stage, work completed, upcoming inspections, open change orders) plus an
editable narrative. Preview/edit, then export PDF or email it to the customer.
"""
from io import BytesIO
from datetime import date, datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    send_file,
)
from flask_login import login_required, current_user

from extensions import db
from models import Customer, WeeklyReport, ChangeOrder
from quote_routes import COMPANY, LOGO_PATH, _pdf_text, safe_filename

report_bp = Blueprint('reports', __name__, url_prefix='/reports')

LOOK_AHEAD_DAYS = 14


def _owned_report_or_404(report_id):
    return WeeklyReport.query.filter_by(
        id=report_id, user_id=current_user.id).first_or_404()


def _owned_customer_or_404(customer_id):
    return Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()


def _week_bounds(for_date=None):
    d = for_date or date.today()
    start = d - timedelta(days=d.weekday())   # Monday
    return start, start + timedelta(days=6)   # Sunday


def project_stage(project):
    """A short stage label: hold points → lot release → status."""
    if getattr(project, 'hold_points', None):
        passed = [g for g in project.hold_points if g.is_passed]
        return f"Through: {passed[-1].name}" if passed else "Hold points: none passed yet"
    if project.lot_release_required:
        return "Lot released" if project.lot_release_ok else "Not released"
    return project.status or "—"


def _logs_in_week(project, ws, we):
    out = []
    for wl in project.work_logs:
        start = wl.start_date
        end = wl.end_date or wl.start_date
        if start and end and start <= we and end >= ws:
            out.append(wl)
    return sorted(out, key=lambda w: (w.start_date or date.min))


def _upcoming_inspections(project):
    today = date.today()
    horizon = today + timedelta(days=LOOK_AHEAD_DAYS)
    out = []
    for perm in getattr(project, 'permits', []):
        for insp in perm.inspections:
            if (insp.scheduled_date and insp.status == 'Scheduled'
                    and today <= insp.scheduled_date <= horizon):
                out.append(insp)
    return sorted(out, key=lambda i: i.scheduled_date)


def build_report_data(customer, ws, we):
    """Live-derived sections for a customer's week."""
    rows = []
    for p in sorted(customer.projects, key=lambda x: (x.name or '')):
        rows.append({
            'project': p,
            'stage': project_stage(p),
            'work_logs': _logs_in_week(p, ws, we),
            'upcoming_inspections': _upcoming_inspections(p),
        })
    open_cos = (ChangeOrder.query
                .filter_by(user_id=customer.user_id, customer_id=customer.id)
                .filter(ChangeOrder.applied_at.is_(None))
                .order_by(ChangeOrder.created_at.desc()).all())
    return {'projects': rows, 'open_change_orders': open_cos}


# ── index / generate ─────────────────────────────────────────────────────────

@report_bp.route('/')
@login_required
def index():
    customers = (Customer.query.filter_by(user_id=current_user.id)
                 .order_by(Customer.name.asc()).all())
    recent = (WeeklyReport.query.filter_by(user_id=current_user.id)
              .order_by(WeeklyReport.created_at.desc()).limit(15).all())
    return render_template('reports/index.html', customers=customers, recent=recent)


@report_bp.route('/customer/<int:customer_id>/generate', methods=['POST'])
@login_required
def generate(customer_id):
    customer = _owned_customer_or_404(customer_id)
    raw = (request.form.get('week_start') or '').strip()
    base = None
    if raw:
        try:
            base = datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            base = None
    ws, we = _week_bounds(base)
    existing = WeeklyReport.query.filter_by(
        user_id=current_user.id, customer_id=customer.id, week_start=ws).first()
    if existing:
        flash('Opened the existing report for that week.', 'success')
        return redirect(url_for('reports.edit', report_id=existing.id))
    report = WeeklyReport(user_id=current_user.id, customer_id=customer.id,
                          week_start=ws, week_end=we)
    db.session.add(report)
    db.session.commit()
    flash('Weekly report generated — review and edit below.', 'success')
    return redirect(url_for('reports.edit', report_id=report.id))


# ── edit / preview ────────────────────────────────────────────────────────────

@report_bp.route('/<int:report_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(report_id):
    report = _owned_report_or_404(report_id)
    if request.method == 'POST':
        report.summary = (request.form.get('summary') or '').strip() or None
        report.delays_issues = (request.form.get('delays_issues') or '').strip() or None
        db.session.commit()
        flash('Report saved.', 'success')
        return redirect(url_for('reports.edit', report_id=report.id))
    data = build_report_data(report.customer, report.week_start, report.week_end)
    return render_template('reports/edit.html', report=report, data=data)


@report_bp.route('/<int:report_id>/delete', methods=['POST'])
@login_required
def delete(report_id):
    report = _owned_report_or_404(report_id)
    db.session.delete(report)
    db.session.commit()
    flash('Report deleted.', 'success')
    return redirect(url_for('reports.index'))


# ── PDF ────────────────────────────────────────────────────────────────────────

def build_weekly_report_pdf(report):
    import os
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image)

    data = build_report_data(report.customer, report.week_start, report.week_end)
    buf = BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.55 * inch,
                            bottomMargin=0.55 * inch, leftMargin=0.7 * inch,
                            rightMargin=0.7 * inch)
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=12)
    section = ParagraphStyle('section', parent=normal, fontName='Helvetica-Bold',
                             fontSize=11, spaceBefore=10, spaceAfter=3)
    sub = ParagraphStyle('sub', parent=normal, fontName='Helvetica-Bold', fontSize=10)
    title = ParagraphStyle('title', parent=styles['Title'], fontSize=15,
                           alignment=TA_CENTER, spaceAfter=0)
    company_name = ParagraphStyle('coname', parent=normal, fontSize=12,
                                  fontName='Helvetica-Bold')

    elems = []
    header = []
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image(LOGO_PATH)
            ratio = logo.imageHeight / float(logo.imageWidth)
            logo.drawWidth = 1.4 * inch
            logo.drawHeight = 1.4 * inch * ratio
            logo.hAlign = 'LEFT'
            header.append(logo)
        except Exception:
            pass
    header.append(Paragraph(COMPANY['name'], company_name))
    header.append(Paragraph(f"{COMPANY['phone']} · {COMPANY['email']}", small))
    elems.append(Table([[header]], colWidths=[7.1 * inch],
                       style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0)])))
    elems.append(Spacer(1, 10))
    elems.append(Paragraph('Weekly Progress Report', title))
    elems.append(Spacer(1, 3))
    elems.append(Paragraph(
        f"{_pdf_text(report.customer.name, 150)} · "
        f"{report.week_start.strftime('%b %d')} – {report.week_end.strftime('%b %d, %Y')}",
        ParagraphStyle('wk', parent=small, alignment=TA_CENTER)))
    elems.append(Spacer(1, 10))

    if report.summary:
        elems.append(Paragraph('Summary', section))
        elems.append(Paragraph(_pdf_text(report.summary, preserve_newlines=True), small))

    for row in data['projects']:
        p = row['project']
        elems.append(Paragraph(f"{_pdf_text(p.name, 150)} — {_pdf_text(row['stage'], 80)}", sub))
        if row['work_logs']:
            for wl in row['work_logs']:
                who = wl.worker.name if wl.worker else 'crew'
                line = f"• {who}: {wl.days_worked or 0:g} day(s)"
                if wl.note:
                    line += f" — {_pdf_text(wl.note, 200)}"
                elems.append(Paragraph(line, small))
        else:
            elems.append(Paragraph('• No work logged this week.', small))
        if row['upcoming_inspections']:
            ins = ', '.join(f"{i.inspection_type} ({i.scheduled_date.strftime('%m/%d')})"
                            for i in row['upcoming_inspections'])
            elems.append(Paragraph(f"Look-ahead inspections: {ins}", small))
        elems.append(Spacer(1, 6))

    if data['open_change_orders']:
        elems.append(Paragraph('Open change orders', section))
        for co in data['open_change_orders']:
            elems.append(Paragraph(
                f"• {co.number or ''} {_pdf_text(co.title, 120)} — "
                f"${(co.total or 0):,.2f} ({co.status})", small))

    if report.delays_issues:
        elems.append(Paragraph('Delays & issues', section))
        elems.append(Paragraph(_pdf_text(report.delays_issues, preserve_newlines=True), small))

    pdf.build(elems)
    buf.seek(0)
    return buf


@report_bp.route('/<int:report_id>/pdf')
@login_required
def pdf(report_id):
    report = _owned_report_or_404(report_id)
    buf = build_weekly_report_pdf(report)
    name = safe_filename(report.customer.name,
                         report.week_start.strftime('%Y-%m-%d'), 'WeeklyReport')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}.pdf')


# ── email ──────────────────────────────────────────────────────────────────────

def send_weekly_report_email(report):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials
    import base64

    customer = report.customer
    if not customer.email:
        return False, 'This customer has no email address on file.'
    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    period = f"{report.week_start.strftime('%b %d')} – {report.week_end.strftime('%b %d, %Y')}"
    html = (f"<p>Please find attached the weekly progress report for {period}.</p>"
            f"<p>{COMPANY['name']}<br>{COMPANY['phone']}</p>")
    msg = MIMEMultipart('mixed')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = f"Weekly progress report — {period}"
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)
    att = MIMEApplication(build_weekly_report_pdf(report).read(), _subtype='pdf')
    name = safe_filename(customer.name, report.week_start.strftime('%Y-%m-%d'), 'WeeklyReport')
    att.add_header('Content-Disposition', 'attachment', filename=f'{name}.pdf')
    msg.attach(att)
    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True, f'Weekly report emailed to {customer.email}.'


@report_bp.route('/<int:report_id>/email', methods=['POST'])
@login_required
def email(report_id):
    report = _owned_report_or_404(report_id)
    try:
        ok, message = send_weekly_report_email(report)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        ok, message = False, f'Email failed: {exc}'
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('reports.edit', report_id=report.id))
