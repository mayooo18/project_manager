from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, BooleanField, SubmitField, IntegerField
from wtforms import TextAreaField, DateField, SelectField, FileField, DecimalField, TextAreaField, PasswordField
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from wtforms_sqlalchemy.fields import QuerySelectField
from flask_wtf.file import FileAllowed, FileField
from models import EXPENSE_CATEGORIES

class WorkerForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    contact = StringField('Contact', validators= [Length(max=100)])
    daily_rate = FloatField('Daily Rate', validators= [DataRequired(), NumberRange(min=0)])
    active = BooleanField('Active', default=True)
    phone = StringField('Phone (for crew login)', validators=[Optional(), Length(max=30)])
    pin = StringField('PIN (4–6 digits — set or reset; leave blank to keep)',
                      validators=[Optional(), Length(min=4, max=6)])
    submit= SubmitField('Submit')

class ProjectForm(FlaskForm):
    name = StringField('Job Name', validators=[DataRequired()])
    customer_id = SelectField('Customer', coerce=int, validators=[Optional()])
    description = TextAreaField('Description')
    address = StringField('Address')
    start_date = DateField('Start Date', format='%Y-%m-%d')
    status = SelectField('Status', choices=[('Active', 'Active'), ('Completed', 'Completed'), ('On Hold', 'On Hold')])
    submit = SubmitField('Add Job')

class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')

class VehicleForm(FlaskForm):
    name = StringField('Vehicle Name', validators=[DataRequired()])
    vehicle_type = SelectField('Type', choices=[('Vehicle', 'Vehicle'), ('Trailer', 'Trailer'), ('Equipment', 'Equipment')])
    make = StringField('Make', validators=[Optional()])
    model = StringField('Model', validators=[Optional()])
    year = IntegerField('Year', validators=[Optional(), NumberRange(min=1900, max=2100)])
    vin = StringField('VIN', validators=[Optional(), Length(max=17)])
    plate_number = StringField('Plate Number', validators=[Optional()])
    plate_expiration = DateField('Plate Expiration', format='%Y-%m-%d', validators=[Optional()])
    registration_expiration = DateField('Registration (Tags) Expiration', format='%Y-%m-%d', validators=[Optional()])
    insurance_provider = StringField('Insurance Provider', validators=[Optional()])
    insurance_policy_number = StringField('Insurance Policy Number', validators=[Optional()])
    insurance_expiration = DateField('Insurance Expiration', format='%Y-%m-%d', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save Vehicle')
    
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
    project_id = SelectField('Job', coerce=int, validators=[DataRequired()])
    start_date = DateField('From', format='%Y-%m-%d', validators=[DataRequired()])
    end_date = DateField('To', format='%Y-%m-%d', validators=[DataRequired()])
    days_worked = FloatField('Days Worked', validators=[DataRequired(),])
    note = TextAreaField('Note (optional)')
    create_payment = BooleanField(
        "Also record a labor payment now — only for workers who don't clock in "
        "on the crew app (the time clock records it automatically)", default=False)
    submit = SubmitField('Log Work')

class WorkLogFilterForm(FlaskForm):
    worker_id = SelectField('Worker', coerce=int)
    project_id = SelectField('Job', coerce=int)
    start_date = DateField('From', format='%Y-%m-%d', validators=[], default=None)
    end_date = DateField('To', format='%Y-%m-%d', validators=[], default=None)
    submit = SubmitField('Filter')

class PaymentForm(FlaskForm):
    worker_id = SelectField('Worker (optional)', coerce=int, choices=[], validators=[Optional()])
    project_id = SelectField('Job (optional)', coerce=int, choices=[], validators=[Optional()])
    amount = FloatField('Amount', validators=[DataRequired()])
    payment_date = DateField('Payment Date', format='%Y-%m-%d', validators=[DataRequired()])
    method = StringField('Method', validators=[Optional()])
    note = TextAreaField('Note', validators=[Optional()])
    receipt = FileField('Receipt', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'pdf'], 'Images and PDFs only')])
    submit = SubmitField('Add Payment')


class PaymentFilterForm(FlaskForm):
    worker_id = SelectField('Worker', coerce=int, validators=[Optional()])
    start_date = DateField('From', format='%Y-%m-%d', validators=[Optional()])
    end_date = DateField('To', format='%Y-%m-%d', validators=[Optional()])
    min_amount = DecimalField('Min Amount', validators=[Optional()])
    max_amount = DecimalField('Max Amount', validators=[Optional()])
    submit = SubmitField('Filter')

class ExpenseForm(FlaskForm):
    project_id = SelectField('Job', coerce=int, validators=[DataRequired()])
    description = StringField('Description', validators=[Optional()])
    amount= FloatField('Amount' , validators=[Optional()])
    category = SelectField('Category', choices=EXPENSE_CATEGORIES, validators=[DataRequired()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    note = TextAreaField('Note')
    receipt = FileField('Receipt photo (optional)', validators=[FileAllowed(
        ['jpg', 'jpeg', 'png', 'heic', 'webp', 'gif', 'pdf'], 'Photos or PDF only')])
    submit = SubmitField('Add Expense')

class FilterForm(FlaskForm):
    project_id = SelectField('Job', coerce=int)
    worker_id = SelectField('Worker', coerce=int)
    start_date = DateField('From', format='%Y-%m-%d')
    end_date = DateField('To', format='%Y-%m-%d')
    submit = SubmitField('Filter')
    
class IncomeForm(FlaskForm):
    project_id = SelectField('Job', coerce=int, validators=[DataRequired()])
    amount = FloatField('Amount', validators=[DataRequired()])
    source = StringField('Source', validators=[Optional()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    note = TextAreaField('Note', validators=[Optional()])
    submit = SubmitField('Add Income')

    

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class UserAdminForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(max=64)])
    password = PasswordField('Temporary password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Create foreman account')


class GcDocumentForm(FlaskForm):
    doc_kind = SelectField('Document Type', choices=[
        ('conditional_progress', 'Conditional Waiver — Progress Payment'),
        ('unconditional_progress', 'Unconditional Waiver — Progress Payment'),
        ('conditional_final', 'Conditional Waiver — Final Payment'),
        ('unconditional_final', 'Unconditional Waiver — Final Payment'),
        ('completion', 'Certificate of Completion'),
    ], default='conditional_progress')
    project_id = SelectField('Job', coerce=int, validators=[Optional()])
    customer_id = SelectField('Customer', coerce=int, validators=[Optional()])
    owner_name = StringField('Owner Name', validators=[Optional(), Length(max=150)])
    property_address = StringField('Property Address', validators=[Optional(), Length(max=250)])
    amount = FloatField('Amount', validators=[Optional()])
    through_date = DateField('Through / Completion Date', format='%Y-%m-%d', validators=[Optional()])
    check_number = StringField('Check #', validators=[Optional(), Length(max=60)])
    exceptions = TextAreaField('Exceptions / Disputed Amounts', validators=[Optional()])
    notes = TextAreaField('Scope / Notes', validators=[Optional()])
    submit = SubmitField('Save Document')


class PermitForm(FlaskForm):
    project_id = SelectField('Job', coerce=int, validators=[Optional()])
    permit_type = StringField('Permit Type', validators=[Optional(), Length(max=80)])
    permit_number = StringField('Permit #', validators=[Optional(), Length(max=80)])
    issuing_authority = StringField('Issuing Authority', validators=[Optional(), Length(max=120)])
    status = SelectField('Status', choices=[
        ('Applied', 'Applied'),
        ('Issued', 'Issued'),
        ('Expired', 'Expired'),
        ('Finaled', 'Finaled'),
        ('Closed', 'Closed'),
    ], default='Applied')
    applied_date = DateField('Applied', format='%Y-%m-%d', validators=[Optional()])
    issued_date = DateField('Issued', format='%Y-%m-%d', validators=[Optional()])
    expiration_date = DateField('Expiration', format='%Y-%m-%d', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save Permit')


class InspectionForm(FlaskForm):
    inspection_type = StringField('Inspection', validators=[DataRequired(), Length(max=80)])
    scheduled_date = DateField('Scheduled', format='%Y-%m-%d', validators=[Optional()])
    status = SelectField('Status', choices=[
        ('Scheduled', 'Scheduled'),
        ('Passed', 'Passed'),
        ('Failed', 'Failed'),
        ('Cancelled', 'Cancelled'),
    ], default='Scheduled')
    result_notes = TextAreaField('Result / Notes', validators=[Optional()])
    submit = SubmitField('Add Inspection')


class LicenseForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=150)])
    credential_type = SelectField('Type', choices=[
        ('License', 'License'),
        ('Insurance', 'Insurance'),
        ('Bond', 'Bond'),
        ('Certification', 'Certification'),
    ], default='License')
    number = StringField('Number', validators=[Optional(), Length(max=80)])
    issuer = StringField('Issuer', validators=[Optional(), Length(max=120)])
    issued_date = DateField('Issued', format='%Y-%m-%d', validators=[Optional()])
    expiration_date = DateField('Expiration / Renewal', format='%Y-%m-%d', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save License')


class SubcontractorForm(FlaskForm):
    name = StringField('Name / Company', validators=[DataRequired(), Length(max=150)])
    trade = StringField('Trade', validators=[Optional(), Length(max=80)])
    contact_name = StringField('Contact Name', validators=[Optional(), Length(max=120)])
    phone = StringField('Phone', validators=[Optional(), Length(max=30)])
    email = StringField('Email', validators=[Optional(), Length(max=150)])
    license_number = StringField('License #', validators=[Optional(), Length(max=80)])
    license_expiration = DateField('License Expiration', format='%Y-%m-%d', validators=[Optional()])
    insurance_carrier = StringField('Insurance Carrier', validators=[Optional(), Length(max=120)])
    insurance_policy_number = StringField('Insurance Policy #', validators=[Optional(), Length(max=80)])
    insurance_expiration = DateField('Insurance Expiration', format='%Y-%m-%d', validators=[Optional()])
    w9_on_file = BooleanField('W-9 on file', default=False)
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save Subcontractor')


class CustomerForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=150)])
    email = StringField('Email', validators=[Optional(), Length(max=150)])
    phone = StringField('Phone', validators=[Optional(), Length(max=30)])
    address = StringField('Address', validators=[Optional(), Length(max=250)])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save Customer')