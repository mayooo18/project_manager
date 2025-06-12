from flask import Flask, render_template, redirect, request, url_for, flash
from flask_wtf.csrf import CSRFProtect
from extensions import db  # ← import from extensions now
from forms import WorkerForm
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


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
 