from flask import Flask, render_template, redirect, request, url_for, flash
from flask_wtf.csrf import CSRFProtect, CSRFError
from extensions import db  
from forms import WorkerForm, ProjectForm, FileUploadForm, WorkLogForm, WorkLogFilterForm
from models import  Project, ProjectFile, WorkLog
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.config.from_object("config.Config")

db.init_app(app)
csrf = CSRFProtect(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


from models import Worker

@app.route('/')
def home():
    return render_template("home.html")

@app.route('/workers', methods=['GET', 'POST'])
def workers():
    form = WorkerForm()
    if form.validate_on_submit():
        new_worker = Worker(
            name=form.name.data,
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
def toggle_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    worker.active = not worker.active
    db.session.commit()
    flash(f'Worker {"activated" if worker.active else "deactivated"} successfully.')
    return redirect(url_for('workers'))

@app.route('/delete_worker/<int:worker_id>', methods=['POST'])
def delete_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    db.session.delete(worker)
    db.session.commit()
    flash('Worker deleted successfully.')
    return redirect(url_for('workers'))

# Route for Projects
@app.route('/projects', methods=['GET', 'POST'])
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
        
    return render_template('projects.html', project_form=project_form, file_form=file_form, projects=filtered_projects)


@app.route('/upload_file/<int:project_id>', methods=['POST'])
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
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    flash('Project deleted successfully.')
    return redirect(url_for('projects'))

@app.route('/delete_file/<int:file_id>', methods=['POST'])
def delete_file(file_id):
    file = ProjectFile.query.get_or_404(file_id)
    db.session.delete(file)
    db.session.commit()
    flash("File deleted.")
    return redirect(url_for('projects'))


@app.route('/edit_file/<int:file_id>', methods=['GET', 'POST'])
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
def delete_work_log(log_id):
    log = WorkLog.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    flash('Work log deleted successfully.')
    return redirect(url_for('work_logs'))






if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
 