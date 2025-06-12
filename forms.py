from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange

class WorkerForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    contact = StringField('Contact', validators= [Length(max=100)])
    hourly_rate = FloatField('Hourly Rate', validators= [DataRequired(), NumberRange(min=0)])
    active = BooleanField('Active', default=True)
    submit= SubmitField('Submit')
