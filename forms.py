from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, BooleanField, SubmitField
from wtforms import TextAreaField, DateField, SelectField, FileField, DecimalField, TextAreaField, PasswordField
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from wtforms_sqlalchemy.fields import QuerySelectField
from flask_wtf.file import FileAllowed, FileField

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

class PaymentForm(FlaskForm):
    worker_id = SelectField('Worker (optional)', coerce=int, choices=[], validators=[Optional()])
    project_id = SelectField('Project (optional)', coerce=int, choices=[], validators=[Optional()])
    amount = FloatField('Amount', validators=[DataRequired()])
    payment_date = DateField('Payment Date', format='%Y-%m-%d', validators=[DataRequired()])
    method = StringField('Method', validators=[Optional()])
    note = TextAreaField('Note', validators=[Optional()])
    submit = SubmitField('Add Payment')


class PaymentFilterForm(FlaskForm):
    worker_id = SelectField('Worker', coerce=int, validators=[Optional()])
    start_date = DateField('From', format='%Y-%m-%d', validators=[Optional()])
    end_date = DateField('To', format='%Y-%m-%d', validators=[Optional()])
    min_amount = DecimalField('Min Amount', validators=[Optional()])
    max_amount = DecimalField('Max Amount', validators=[Optional()])
    submit = SubmitField('Filter')

class ExpenseForm(FlaskForm):
    project_id = SelectField('Project', coerce=int, validators=[DataRequired()])
    description = StringField('Description', validators=[Optional()])
    amount= FloatField('Amount' , validators=[Optional()])
    category = SelectField('Category', choices=[
        ('materials', 'Materials'),
        ('labor', 'Labor'),
        ('equipment', 'Equipment'),
        ('misc', 'Miscellaneous')
    ], validators=[DataRequired()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    note = TextAreaField('Note')
    receipt = FileField('Receipt', validators=[FileAllowed(['jpg', 'png', 'pdf'], 'Images and PDFs only')])
    submit = SubmitField('Add Expense')

class FilterForm(FlaskForm):
    project_id = SelectField('Project', coerce=int)
    worker_id = SelectField('Worker', coerce=int)
    start_date = DateField('From', format='%Y-%m-%d')
    end_date = DateField('To', format='%Y-%m-%d')
    submit = SubmitField('Filter')
    
class IncomeForm(FlaskForm):
    project_id = SelectField('Project', coerce=int, validators=[DataRequired()])
    amount = FloatField('Amount', validators=[DataRequired()])
    source = StringField('Source', validators=[Optional()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    note = TextAreaField('Note', validators=[Optional()])
    submit = SubmitField('Add Income')

    

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')
