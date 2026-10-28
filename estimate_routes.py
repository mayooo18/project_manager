"""Cost estimate per lot (F15).

Takeoff-based estimates: concrete yardage computed from dimensions (with waste),
plus flexible cost lines for rebar/stone/fill/subs/labor/equipment, compared to
the contract price for a margin %. Copyable to new lots with the same plan.
"""
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from extensions import db
from models import (
    Project, Contract, CostEstimate, CostEstimateLine, ESTIMATE_LINE_CATEGORIES,
)

estimate_bp = Blueprint('estimates', __name__, url_prefix='/estimates')

DIM_FIELDS = [
    'footing_lf', 'footing_width_in', 'footing_depth_in', 'wall_lf',
    'wall_height_ft', 'wall_thickness_in', 'slab_area_sf', 'slab_thickness_in',
    'waste_pct', 'concrete_per_cy', 'equipment_monthly',
]


def _owned_estimate_or_404(estimate_id):
    return CostEstimate.query.filter_by(
        id=estimate_id, user_id=current_user.id).first_or_404()


def _owned_project_or_404(project_id):
    project = Project.query.get_or_404(project_id)
    ok = (project.customer and project.customer.user_id == current_user.id) or \
         any(c.user_id == current_user.id for c in project.contracts)
    if not ok:
        abort(404)
    return project


def _f(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _project_contract(project):
    for c in project.contracts:
        if c.user_id == current_user.id:
            return c
    return None


# ── create / edit ────────────────────────────────────────────────────────────

@estimate_bp.route('/job/<int:project_id>/new', methods=['POST'])
@login_required
def new(project_id):
    project = _owned_project_or_404(project_id)
    con = _project_contract(project)
    est = CostEstimate(user_id=current_user.id, project_id=project.id,
                       contract_id=con.id if con else None,
                       name=(request.form.get('name') or 'Estimate').strip() or 'Estimate',
                       waste_pct=0.0, equipment_lots=1)
    db.session.add(est)
    db.session.commit()
    flash('Cost estimate created — enter the takeoff below.', 'success')
    return redirect(url_for('estimates.edit', estimate_id=est.id))


@estimate_bp.route('/<int:estimate_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(estimate_id):
    est = _owned_estimate_or_404(estimate_id)
    if request.method == 'POST':
        est.name = (request.form.get('name') or 'Estimate').strip() or 'Estimate'
        for f in DIM_FIELDS:
            setattr(est, f, _f(request.form.get(f)))
        try:
            est.equipment_lots = max(int(request.form.get('equipment_lots') or 1), 1)
        except (TypeError, ValueError):
            est.equipment_lots = 1
        est.price_override = _f(request.form.get('price_override'))
        db.session.commit()
        flash('Estimate saved.', 'success')
        return redirect(url_for('estimates.edit', estimate_id=est.id))
    projects = (Project.query.join(Project.customer)
                .filter_by(user_id=current_user.id)
                .order_by(Project.name.asc()).all())
    return render_template('estimates/edit.html', est=est, projects=projects,
                           categories=ESTIMATE_LINE_CATEGORIES)


@estimate_bp.route('/<int:estimate_id>/line/add', methods=['POST'])
@login_required
def add_line(estimate_id):
    est = _owned_estimate_or_404(estimate_id)
    desc = (request.form.get('description') or '').strip()
    if not desc:
        flash('Describe the cost line.', 'error')
        return redirect(url_for('estimates.edit', estimate_id=est.id))
    cat = request.form.get('category', 'Material')
    if cat not in ESTIMATE_LINE_CATEGORIES:
        cat = 'Other'
    db.session.add(CostEstimateLine(
        estimate_id=est.id, category=cat, description=desc,
        quantity=_f(request.form.get('quantity')) or 1,
        unit_cost=_f(request.form.get('unit_cost')) or 0))
    db.session.commit()
    return redirect(url_for('estimates.edit', estimate_id=est.id))


@estimate_bp.route('/line/<int:line_id>/delete', methods=['POST'])
@login_required
def delete_line(line_id):
    line = CostEstimateLine.query.get_or_404(line_id)
    est = _owned_estimate_or_404(line.estimate_id)
    db.session.delete(line)
    db.session.commit()
    return redirect(url_for('estimates.edit', estimate_id=est.id))


# ── copy to another lot ──────────────────────────────────────────────────────

@estimate_bp.route('/<int:estimate_id>/copy', methods=['POST'])
@login_required
def copy(estimate_id):
    est = _owned_estimate_or_404(estimate_id)
    target = _owned_project_or_404(request.form.get('target_project_id', type=int) or 0)
    con = _project_contract(target)
    clone = CostEstimate(
        user_id=current_user.id, project_id=target.id,
        contract_id=con.id if con else None,
        name=f"{est.name} (copy)", waste_pct=est.waste_pct,
        concrete_per_cy=est.concrete_per_cy, equipment_monthly=est.equipment_monthly,
        equipment_lots=est.equipment_lots, price_override=est.price_override)
    for f in ['footing_lf', 'footing_width_in', 'footing_depth_in', 'wall_lf',
              'wall_height_ft', 'wall_thickness_in', 'slab_area_sf', 'slab_thickness_in']:
        setattr(clone, f, getattr(est, f))
    db.session.add(clone)
    db.session.flush()
    for ln in est.lines:
        clone.lines.append(CostEstimateLine(
            category=ln.category, description=ln.description,
            quantity=ln.quantity, unit_cost=ln.unit_cost))
    db.session.commit()
    flash(f'Estimate copied to {target.name}.', 'success')
    return redirect(url_for('estimates.edit', estimate_id=clone.id))


@estimate_bp.route('/<int:estimate_id>/delete', methods=['POST'])
@login_required
def delete(estimate_id):
    est = _owned_estimate_or_404(estimate_id)
    pid = est.project_id
    db.session.delete(est)
    db.session.commit()
    flash('Estimate deleted.', 'success')
    return redirect(url_for('project_detail', project_id=pid))
