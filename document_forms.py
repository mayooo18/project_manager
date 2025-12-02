from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DateField, FloatField, SubmitField
from wtforms.validators import DataRequired, Optional
from datetime import date

class DocumentForm(FlaskForm):
    doc_type = SelectField('Document Type', 
                          choices=[('PROPOSAL', 'Proposal'), 
                                   ('INVOICE', 'Invoice'), 
                                   ('CONTRACT', 'Contract')],
                          validators=[DataRequired()])
    
    invoice_number = StringField('Invoice/Proposal Number', 
                                validators=[DataRequired()],
                                default='N/A')
    
    date = DateField('Date', 
                    format='%Y-%m-%d', 
                    default=date.today,
                    validators=[DataRequired()])
    
    client_name = StringField('Client Name', validators=[DataRequired()])
    
    client_address = StringField('Client Address', validators=[DataRequired()])
    
    project_name = StringField('Project/Job Name', validators=[DataRequired()])
    
    scope_of_work = TextAreaField('Scope of Work', validators=[DataRequired()])
    
    materials_notes = TextAreaField('Materials Notes', validators=[Optional()])
    
    total_price = FloatField('Total Price', validators=[DataRequired()])
    
    po_number = StringField('P.O. Number', validators=[Optional()])
    
    submit = SubmitField('Generate Document')
