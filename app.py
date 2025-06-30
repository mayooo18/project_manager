from flask import Flask, render_template, redirect, request, url_for, flash
from flask_wtf.csrf import CSRFProtect, CSRFError
from extensions import db  
from forms import WorkerForm, ProjectForm, FileUploadForm, WorkLogForm, WorkLogFilterForm, PaymentForm, PaymentFilterForm, ExpenseForm, IncomeForm, LoginForm
from models import  Project, ProjectFile, WorkLog, Worker, Payment, Expense, Income
from werkzeug.utils import secure_filename
import os
from flask_login import LoginManager, login_required, current_user, login_user, logout_user




app = Flask(__name__)
app.config.from_object("config.Config")

db.init_app(app)
csrf = CSRFProtect(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


from models import Worker , User


login_manager = LoginManager()
login_manager.login_view = 'login'  # Redirect to login page if not authenticated
login_manager.init_app(app)



@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Logged in successfully.')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.')
            
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.')
    return redirect(url_for('login'))


@app.route('/')
@login_required
def home():
    worker_count = Worker.query.count()
    project_count = Project.query.count()
    return render_template("home.html", worker_count=worker_count, project_count=project_count)

@app.route('/workers', methods=['GET', 'POST'])
@login_required
def workers():
    form = WorkerForm()
    if form.validate_on_submit():
        new_worker = Worker(
            name=form.  name.data,
            contact=form.contact.data,
            hourly_rate=form.hourly_rate.data,
            active=form.active.data
        )
        db.session.add(new_worker)
        db.session.commit()
        flash('Worker added successfully')
        return redirect(url_for('workers'))

    all_workers = Worker.query.all()
    return render_template('workers.html', form=form, workers=all_workers)

@app.route('/edit_worker/<int:worker_id>', methods=['GET', 'POST'])
@login_required
def edit_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    form = WorkerForm(obj=worker)

    if form.validate_on_submit():
        worker.name = form.name.data
        worker.contact = form.contact.data
        worker.hourly_rate = form.hourly_rate.data
        worker.active = form.active.data
        db.session.commit()
        flash('Worker updated successfully.')
        return redirect(url_for('workers'))

    return render_template('edit_worker.html', form=form)

@app.route('/toggle_worker/<int:worker_id>')
@login_required
def toggle_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    worker.active = not worker.active
    db.session.commit()
    flash(f'Worker {"activated" if worker.active else "deactivated"} successfully.')
    return redirect(url_for('workers'))

@app.route('/delete_worker/<int:worker_id>', methods=['POST'])
@login_required
def delete_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    db.session.delete(worker)
    db.session.commit()
    flash('Worker deleted successfully.')
    return redirect(url_for('workers'))

# Route for Projects
@app.route('/projects', methods=['GET', 'POST'])
@login_required
def projects():
    project_form = ProjectForm()
    file_form = FileUploadForm()
    all_projects = Project.query.all()

    selected_category = request.args.get('category', 'all')
    filtered_projects = []

    for project in all_projects:
        filtered_files = project.files
        if selected_category and selected_category != 'all':
            filtered_files = [f for f in project.files if f.category == selected_category]
    
    # Attach filtered files without overriding actual .files
        project.filtered_files = filtered_files
        filtered_projects.append(project)


    if project_form.validate_on_submit() and 'add_project' in request.form:
        new_project = Project(
            name=project_form.name.data,
            description=project_form.description.data,
            address=project_form.address.data,
            start_date=project_form.start_date.data,
            status=project_form.status.data
        )
        db.session.add(new_project)
        db.session.commit()
        flash('Project added successfully')
        return redirect(url_for('projects'))
        
    return render_template('projects.html', project_form=project_form, file_form=file_form, projects=filtered_projects, selected_category = selected_category)


@app.route('/upload_file/<int:project_id>', methods=['POST'])
@login_required
def upload_file(project_id):
    form= FileUploadForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        new_file = ProjectFile(
            project_id=project_id,
            filename=filename,
            filepath=filepath,
            category=form.category.data,
            note=form.note.data if form.category.data == 'misc' else None
        )
        db.session.add(new_file)
        db.session.commit()
        flash('File uploaded successfully')
    return redirect(url_for('projects'))


@app.route('/edit_project/<int:project_id>', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)
    form = ProjectForm(obj=project)

    if form.validate_on_submit():
        project.name = form.name.data
        project.description = form.description.data
        project.address = form.address.data
        project.start_date = form.start_date.data
        project.status = form.status.data
        db.session.commit()
        flash('Project updated successfully.')
        return redirect(url_for('projects'))

    return render_template('edit_project.html', form=form, project=project)

@app.route('/delete_project/<int:project_id>', methods=['POST'])
@login_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    flash('Project deleted successfully.')
    return redirect(url_for('projects'))

@app.route('/delete_file/<int:file_id>', methods=['POST'])
@login_required
def delete_file(file_id):
    file = ProjectFile.query.get_or_404(file_id)
    db.session.delete(file)
    db.session.commit()
    flash("File deleted.")
    return redirect(url_for('projects'))


@app.route('/edit_file/<int:file_id>', methods=['GET', 'POST'])
@login_required
def edit_file(file_id):
    file = ProjectFile.query.get_or_404(file_id)
    form = FileUploadForm(obj=file)

    if form.validate_on_submit():
        file.category = form.category.data
        file.note = form.note.data
        db.session.commit()
        flash("File updated.")
        return redirect(url_for('projects'))

    return render_template('edit_file.html', form=form, file=file)

# Route for Work Logs
@app.route('/work_logs', methods=['GET', 'POST'])
@login_required
def work_logs():
    form = WorkLogForm()
    filter_form = WorkLogFilterForm()

    # Set dropdown choices
    workers = Worker.query.all()
    projects = Project.query.all()
    form.worker_id.choices = [(w.id, w.name) for w in workers]
    form.project_id.choices = [(p.id, p.name) for p in projects]
    filter_form.worker_id.choices = [(-1, 'All')] + [(w.id, w.name) for w in workers]
    filter_form.project_id.choices = [(-1, 'All')] + [(p.id, p.name) for p in projects]


    # Handle new log submission
    if form.validate_on_submit() and 'submit' in request.form:
        new_log = WorkLog(
            worker_id=form.worker_id.data,
            project_id=form.project_id.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            hours_worked=form.hours_worked.data,
            note=form.note.data
        )
        db.session.add(new_log)
        db.session.commit()
        flash('Work log added successfully')
        return redirect(url_for('work_logs'))

    # Handle filtering
    logs_query = WorkLog.query
    if filter_form.validate_on_submit() and 'filter' in request.form:
        if filter_form.worker_id.data != -1:
            logs_query = logs_query.filter_by(worker_id=filter_form.worker_id.data)
        if filter_form.project_id.data != -1:
            logs_query = logs_query.filter_by(project_id=filter_form.project_id.data)
        if filter_form.start_date.data:
            logs_query = logs_query.filter(WorkLog.start_date >= filter_form.start_date.data)
        if filter_form.end_date.data:
            logs_query = logs_query.filter(WorkLog.end_date <= filter_form.end_date.data)

    logs = logs_query.order_by(WorkLog.start_date.desc()).all()

    return render_template(
        'work_logs.html',
        form=form,
        filter_form=filter_form,
        logs=logs
    )




@app.route('/work_logs/edit/<int:log_id>', methods=['GET', 'POST'])
@login_required
def edit_work_log(log_id):
    log = WorkLog.query.get_or_404(log_id)
    form = WorkLogForm(obj=log)

    form.worker_id.choices = [(w.id, w.name) for w in Worker.query.all()]
    form.project_id.choices = [(p.id, p.name) for p in Project.query.all()]

    if form.validate_on_submit():
        log.worker_id = form.worker_id.data
        log.project_id = form.project_id.data
        log.start_date = form.start_date.data
        log.end_date = form.end_date.data
        log.hours_worked = form.hours_worked.data
        log.note = form.note.data
        db.session.commit()
        flash('Work log updated successfully')
        return redirect(url_for('work_logs'))

    return render_template('edit_work_log.html', form=form, log=log)



@app.route('/work_logs/delete/<int:log_id>', methods=['POST'])
@login_required
def delete_work_log(log_id):
    log = WorkLog.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    flash('Work log deleted successfully.')
    return redirect(url_for('work_logs'))


@app.route('/payments', methods=['GET', 'POST'])
@login_required
def payments():
    form = PaymentForm()
    filter_form = PaymentFilterForm()
    form.worker_id.choices = [(0, '---')] + [(w.id, w.name) for w in Worker.query.all()]
    form.project_id.choices = [(0, '---')] + [(p.id, p.name) for p in Project.query.all()]
    
    # Handle submission
    if form.validate_on_submit():
        new_payment = Payment(
            worker_id=form.worker_id.data if form.worker_id.data != 0 else None,
            project_id=form.project_id.data if form.project_id.data != 0 else None,
            amount=form.amount.data,
            payment_date=form.payment_date.data,
            method=form.method.data,
            note=form.note.data
        )
        db.session.add(new_payment)
        db.session.commit()
        flash('Payment recorded successfully')
        return redirect(url_for('payments'))

    # Handle filter
    payments_query = Payment.query

    worker_id = request.args.get('worker_id', type=int)
    if worker_id:
        payments_query = payments_query.filter_by(worker_id=worker_id)

    start_date = request.args.get('start_date')
    if start_date:
        payments_query = payments_query.filter(Payment.payment_date >= start_date)

    end_date = request.args.get('end_date')
    if end_date:
        payments_query = payments_query.filter(Payment.payment_date <= end_date)

    min_amount = request.args.get('min_amount', type=float)
    if min_amount is not None:
        payments_query = payments_query.filter(Payment.amount >= min_amount)

    max_amount = request.args.get('max_amount', type=float)
    if max_amount is not None:
        payments_query = payments_query.filter(Payment.amount <= max_amount)

    filtered_payments = payments_query.order_by(Payment.payment_date.desc()).all()

    return render_template('payments.html',
        form=form,
        payments=filtered_payments,
        filter_form=filter_form,
        workers=Worker.query.all()
    )

@app.route('/payments/edit/<int:payment_id>', methods=['GET', 'POST'])
@login_required
def edit_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    form = PaymentForm(obj=payment)
    form.worker_id.choices = [(w.id, w.name) for w in Worker.query.all()]

    if form.validate_on_submit():
        payment.worker_id = form.worker_id.data
        payment.amount = form.amount.data
        payment.payment_date = form.payment_date.data
        payment.method = form.method.data
        payment.note = form.note.data
        db.session.commit()
        flash('Payment updated successfully.')
        return redirect(url_for('payments'))

    return render_template('edit_payment.html', form=form, payment=payment)
    

@app.route('/payments/delete/<int:payment_id>', methods=['POST'])
@login_required
def delete_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    db.session.delete(payment)
    db.session.commit()
    flash('Payment deleted successfully.')
    return redirect(url_for('payments'))


@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    form = ExpenseForm()
    form.project_id.choices = [(p.id, p.name) for p in Project.query.all()]

    if form.validate_on_submit():
        filename = None
        if form.receipt.data:
            receipt_file = form.receipt.data
            filename = secure_filename(receipt_file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            receipt_file.save(filepath)

        new_expense = Expense(
            project_id=form.project_id.data,
            description=form.description.data,
            amount=form.amount.data,
            category=form.category.data,
            date=form.date.data,
            note=form.note.data,
            receipt_filename=filename
        )
        db.session.add(new_expense)
        db.session.commit()
        flash('Expense added successfully')
        return redirect(url_for('expenses'))

    all_expenses = Expense.query.order_by(Expense.date.desc()).all()
    return render_template('expenses.html', form=form, expenses=all_expenses)

@app.route('/expenses/delete/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if expense.receipt_filename:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], expense.receipt_filename))
        except FileNotFoundError:
            pass  # If file doesn't exist, silently ignore
    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted successfully')
    return redirect(url_for('expenses'))



@app.route('/expenses/edit/<int:expense_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    form = ExpenseForm(obj=expense)
    form.project_id.choices = [(p.id, p.name) for p in Project.query.all()]

    if form.validate_on_submit():
        # Update fields
        expense.project_id = form.project_id.data
        expense.description = form.description.data
        expense.amount = form.amount.data
        expense.category = form.category.data
        expense.date = form.date.data
        expense.note = form.note.data

        # Handle new receipt upload
        if form.receipt.data:
            if expense.receipt_filename:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], expense.receipt_filename))
                except FileNotFoundError:
                    pass
            receipt_file = form.receipt.data
            filename = secure_filename(receipt_file.filename)
            receipt_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            expense.receipt_filename = filename

        db.session.commit()
        flash('Expense updated successfully')
        return redirect(url_for('expenses'))

    return render_template('edit_expense.html', form=form)

@app.route('/profitability')
@login_required
def profitability():
    projects = Project.query.all()
    data = []

    for project in projects:
        total_expenses = sum(exp.amount for exp in project.expenses)
        total_income = sum(inc.amount for inc in project.incomes)  # 👈 use incomes from relationship
        profit = total_income - total_expenses

        data.append({
            'project': project.name,
            'expenses': total_expenses,
            'income': total_income,
            'profit': profit
        })

    return render_template('profitability.html', data=data)


@app.route('/income', methods=['GET', 'POST'])
@login_required
def income():
    form = IncomeForm()
    form.project_id.choices = [(p.id, p.name) for p in Project.query.all()]

    if form.validate_on_submit():
        new_income = Income(
            project_id=form.project_id.data,
            amount=form.amount.data,
            source=form.source.data,
            date=form.date.data,
            note=form.note.data
        )
        db.session.add(new_income)
        db.session.commit()
        flash('Income added successfully')
        return redirect(url_for('income'))

    all_income = Income.query.order_by(Income.date.desc()).all()
    return render_template('income.html', form=form, incomes=all_income)


@app.route('/income/edit/<int:income_id>', methods=['GET', 'POST'])
@login_required
def edit_income(income_id):
    income = Income.query.get_or_404(income_id)
    form = IncomeForm(obj=income)
    form.project_id.choices = [(p.id, p.name) for p in Project.query.all()]

    if form.validate_on_submit():
        income.project_id = form.project_id.data
        income.amount = form.amount.data
        income.source = form.source.data
        income.date = form.date.data
        income.note = form.note.data
        db.session.commit()
        flash('Income updated successfully.')
        return redirect(url_for('income'))

    return render_template('edit_income.html', form=form, income=income)

@app.route('/income/delete/<int:income_id>', methods=['POST'])
@login_required
def delete_income(income_id):
    income = Income.query.get_or_404(income_id)
    db.session.delete(income)
    db.session.commit()
    flash('Income deleted successfully.')
    return redirect(url_for('income'))


if __name__ == '__main__':
        with app.app_context():
            db.create_all()
        app.run(debug=True)
 