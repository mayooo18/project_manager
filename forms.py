from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, BooleanField, SubmitField
from wtforms import TextAreaField, DateField, SelectField, FileField, DecimalField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

class WorkerForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    contact = StringField('Contact', validators= [Length(max=100)])
    hourly_rate = FloatField('Hourly Rate', validators= [DataRequired(), NumberRange(min=0)])
    active = BooleanField('Active', default=True)
    submit= SubmitField('Submit')

class ProjectForm(FlaskForm):
    name = StringField('Project Name', validators=[DataRequired()])
    description = TextAreaField('Description')
    address = StringField('Address')
    start_date = DateField('Start Date', format='%Y-%m-%d')
    status = SelectField('Status', choices=[('Active', 'Active'), ('Completed', 'Completed'), ('On Hold', 'On Hold')])
    submit = SubmitField('Add Project')

class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')
    
class FileUploadForm(FlaskForm):
    file = FileField('Upload File', validators=[DataRequired()])
    category = SelectField('Category', choices=[
        ('proposal', 'Proposal'),
        ('contract', 'Contract'),
        ('invoice', 'invoice'),
        ('misc', 'Other')
    ])
    note = StringField('Note', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Upload File')

class WorkLogForm(FlaskForm):
    worker_id = SelectField('Worker', coerce=int, validators=[DataRequired()])
    project_id = SelectField('Project', coerce=int, validators=[DataRequired()])
    start_date = DateField('From', format='%Y-%m-%d', validators=[DataRequired()])
    end_date = DateField('To', format='%Y-%m-%d', validators=[DataRequired()])
    hours_worked = FloatField('Hours Worked', validators=[DataRequired(),])
    note = TextAreaField('Note (optional)')
    submit = SubmitField('Log Work')

class WorkLogFilterForm(FlaskForm):
    worker_id = SelectField('Worker', coerce=int)
    project_id = SelectField('Project', coerce=int)
    start_date = DateField('From', format='%Y-%m-%d', validators=[], default=None)
    end_date = DateField('To', format='%Y-%m-%d', validators=[], default=None)
    submit = SubmitField('Filter')
