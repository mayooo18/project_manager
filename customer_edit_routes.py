"""Edit a customer's contact details (name, email, phone, address, notes).

The Customers page could add, merge and delete customers but not change an
existing one, so a missing email (needed to email contracts) or a wrong
address could only be fixed by re-creating the customer. Owner/admin only;
duplicates by email or phone are refused, same as when adding.
"""
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from forms import CustomerForm
from models import Customer
from quote_routes import _find_duplicate_customer

customer_edit_bp = Blueprint('customer_edit', __name__,
                             url_prefix='/quotes/customers')


@customer_edit_bp.route('/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(customer_id):
    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()
    form = CustomerForm(obj=customer)
    form.submit.label.text = 'Save changes'
    if form.validate_on_submit():
        dup, reason = _find_duplicate_customer(
            form.name.data, form.email.data, form.phone.data,
            exclude_id=customer.id)
        if dup and reason in ('email', 'phone'):
            flash(f'Another customer already has that {reason}: {dup.name}.',
                  'error')
        else:
            form.populate_obj(customer)
            db.session.commit()
            flash('Customer updated.', 'success')
            return redirect(url_for('quotes.customer_detail',
                                    customer_id=customer.id))
    return render_template('customers/edit.html', form=form, customer=customer)
