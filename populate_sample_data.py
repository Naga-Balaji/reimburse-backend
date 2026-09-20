import os
import django
from datetime import date, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from core.models import UserProfile, TravelRequest, ExpenseClaim, ExpenseItem, Approval

# Delete existing data
print("Clearing existing data...")
Approval.objects.all().delete()
ExpenseItem.objects.all().delete()
ExpenseClaim.objects.all().delete()
TravelRequest.objects.all().delete()
UserProfile.objects.all().delete()
User.objects.filter(is_superuser=False).delete()

# Create users based on employee_master.csv
print("Creating users...")

md = User.objects.create_user(username='nandita', email='nandita.shah@nortex.com', password='password123', first_name='Nandita', last_name='Shah')
div_head = User.objects.create_user(username='arvind', email='arvind.rao@nortex.com', password='password123', first_name='Arvind', last_name='Rao')
dept_head = User.objects.create_user(username='meera', email='meera.krishnan@nortex.com', password='password123', first_name='Meera', last_name='Krishnan')
manager = User.objects.create_user(username='suresh', email='suresh.iyer@nortex.com', password='password123', first_name='Suresh', last_name='Iyer')
employee = User.objects.create_user(username='chaitanya', email='chaitanya.reddy@nortex.com', password='password123', first_name='Chaitanya', last_name='Reddy')
employee2 = User.objects.create_user(username='deepa', email='deepa.nair@nortex.com', password='password123', first_name='Deepa', last_name='Nair')
employee3 = User.objects.create_user(username='imran', email='imran.qureshi@nortex.com', password='password123', first_name='Imran', last_name='Qureshi')
finance = User.objects.create_user(username='ravi', email='ravi.menon@nortex.com', password='password123', first_name='Ravi', last_name='Menon')

# Create profiles
UserProfile.objects.create(user=md, role='admin', department='Corporate')
UserProfile.objects.create(user=div_head, role='manager', department='Commercial', reporting_manager=md)
UserProfile.objects.create(user=dept_head, role='manager', department='Sales', reporting_manager=div_head)
UserProfile.objects.create(user=manager, role='manager', department='Sales', reporting_manager=dept_head)
UserProfile.objects.create(user=employee, role='employee', department='Sales', reporting_manager=manager)
UserProfile.objects.create(user=employee2, role='employee', department='Sales', reporting_manager=manager)
UserProfile.objects.create(user=employee3, role='employee', department='Sales', reporting_manager=manager)
UserProfile.objects.create(user=finance, role='finance', department='Finance', reporting_manager=None)

print(f"✓ Created 8 users with role hierarchy")

# Create travel request (approved)
tr1 = TravelRequest.objects.create(
    employee=employee,
    destination='Bengaluru',
    from_date=date(2026, 6, 16),
    to_date=date(2026, 6, 20),
    purpose='Customer meeting + site visit at Vertex Technologies',
    estimated_cost=48000,
    advance_requested=20000,
    status='approved'
)

# Create pending travel request (for manager to approve)
tr2 = TravelRequest.objects.create(
    employee=employee,
    destination='Mumbai',
    from_date=date(2026, 7, 10),
    to_date=date(2026, 7, 13),
    purpose='Client presentation and contract negotiation',
    estimated_cost=35000,
    advance_requested=15000,
    status='pending'
)

# Third travel request from another employee (pending)
tr3 = TravelRequest.objects.create(
    employee=employee2,
    destination='Chennai',
    from_date=date(2026, 8, 5),
    to_date=date(2026, 8, 7),
    purpose='Presales demo at customer HQ',
    estimated_cost=22000,
    advance_requested=10000,
    status='pending'
)

print(f"✓ Created 3 travel requests (1 approved, 2 pending)")

# Create expense claim for TR-1
claim = ExpenseClaim.objects.create(
    travel_request=tr1,
    employee=employee,
    status='draft'
)

# Expense items (using .save which triggers policy validation)
items_data = [
    dict(category='lodging', amount=17250, description='Keys Prime Hotel, Whitefield', proof_reference='hotel_invoice_1188.png',
         check_in_date=date(2026, 6, 16), check_out_date=date(2026, 6, 19), nights=3, city='Bengaluru'),
    dict(category='transport', amount=1415.02, description='Uber: Baner, Pune to Pune Airport', proof_reference='uber_receipt_1.eml'),
    dict(category='transport', amount=743, description='Uber: BLR Airport to Keys Prime Hotel', proof_reference='uber_receipt_2.eml'),
    dict(category='transport', amount=172, description='Uber: Vertex Technologies to Hotel', proof_reference='uber_receipt_3.eml'),
    dict(category='transport', amount=1229.02, description='Uber: PNQ Airport to Baner, Pune', proof_reference='uber_receipt_4.eml'),
    dict(category='entertainment', amount=4000, description='Dinner with Vertex procurement team (4 people)', proof_reference='dinner_bill_18jun.png'),
]

for data in items_data:
    item = ExpenseItem(claim=claim, **data)
    item.save()

print(f"✓ Created claim EC-{claim.id} with {claim.items.count()} items (draft)")

# ─────────────────────────────────────────────
# Historical claims (for AI insights + employee history) — fully approved chain
# ─────────────────────────────────────────────
from datetime import datetime
from django.utils import timezone
from decimal import Decimal
from core.views import ApprovalWorkflowHelper

past_trips = [
    ('Hyderabad', date(2026, 3, 10), date(2026, 3, 12), 32000, 15000, [
        ('lodging', 12000, 'Hyatt Hyderabad · 2 nights', 'hyatt_inv.pdf', date(2026, 3, 10), date(2026, 3, 12), 2, 'Hyderabad'),
        ('transport', 2400, 'Uber airport transfers', 'uber_hyd.eml', None, None, None, None),
        ('meals', 1800, 'Dinner + lunch', 'meals.eml', None, None, None, None),
    ]),
    ('Chennai', date(2026, 4, 5), date(2026, 4, 7), 28000, 12000, [
        ('lodging', 10000, 'Trident Chennai · 2 nights', 'trident.pdf', date(2026, 4, 5), date(2026, 4, 7), 2, 'Chennai'),
        ('transport', 3200, 'Airport + local', 'cab_maa.eml', None, None, None, None),
        ('entertainment', 3500, 'Client dinner', 'dinner_maa.png', None, None, None, None),
    ]),
    ('Mumbai', date(2026, 5, 20), date(2026, 5, 22), 42000, 18000, [
        ('lodging', 14000, 'Taj Mumbai · 2 nights', 'taj_mum.pdf', date(2026, 5, 20), date(2026, 5, 22), 2, 'Mumbai'),
        ('transport', 4500, 'Uber Mumbai', 'uber_mum.eml', None, None, None, None),
        ('meals', 2200, 'Meals', 'meals_mum.eml', None, None, None, None),
        ('entertainment', 5000, 'Team dinner (5 people)', 'dinner_mum.png', None, None, None, None),
    ]),
    ('Delhi', date(2026, 6, 1), date(2026, 6, 3), 36000, 16000, [
        ('lodging', 13500, 'Radisson Delhi · 2 nights', 'radisson.pdf', date(2026, 6, 1), date(2026, 6, 3), 2, 'Delhi'),
        ('transport', 2800, 'Cab transfers', 'cab_del.eml', None, None, None, None),
        ('meals', 1500, 'Meals', 'meals_del.eml', None, None, None, None),
    ]),
]

for dest, from_d, to_d, est, adv, items in past_trips:
    past_tr = TravelRequest.objects.create(
        employee=employee, destination=dest, from_date=from_d, to_date=to_d,
        purpose=f'Customer meeting in {dest}',
        estimated_cost=est, advance_requested=adv, status='approved',
        # Advance was disbursed 5 days before trip
        advance_disbursed_amount=Decimal(str(adv)),
        advance_disbursed_at=timezone.make_aware(datetime.combine(from_d - timedelta(days=5), datetime.min.time().replace(hour=10))),
        advance_disbursed_by=finance,
        advance_disbursement_ref=f'ADV/2026/{100 + past_trips.index((dest, from_d, to_d, est, adv, items)):04d}',
    )
    past_claim = ExpenseClaim.objects.create(
        travel_request=past_tr, employee=employee, status='paid',
        submitted_at=timezone.make_aware(datetime.combine(to_d + timedelta(days=1), datetime.min.time().replace(hour=14))),
    )
    for cat, amt, desc, ref, cin, cout, nights, city in items:
        ExpenseItem(
            claim=past_claim, category=cat, amount=Decimal(str(amt)),
            description=desc, proof_reference=ref,
            check_in_date=cin, check_out_date=cout, nights=nights, city=city,
        ).save()
    # Backfill approval chain based on claim value
    net = float(past_claim.net_reimbursable)
    levels = ApprovalWorkflowHelper.get_required_approval_levels(net)
    for i, level in enumerate(levels):
        approver_map = {'manager': manager, 'dept_head': dept_head, 'div_head': div_head, 'md_ceo': md, 'finance': finance}
        Approval.objects.create(
            claim=past_claim, level=level, decision='approved',
            approver=approver_map.get(level),
            remarks=f'Approved',
            decided_at=timezone.make_aware(datetime.combine(to_d + timedelta(days=i + 2), datetime.min.time().replace(hour=10))),
        )

print(f"✓ Backfilled 4 historical paid claims with complete approval chains")

print("\n=== DEMO CREDENTIALS ===")
print("Employee 1:  chaitanya / password123  (Sales, reports to Suresh)")
print("Employee 2:  deepa / password123      (Sales, reports to Suresh)")
print("Manager:     suresh / password123     (approves Chaitanya's & Deepa's claims)")
print("Dept Head:   meera / password123      (approves Suresh's team)")
print("Div Head:    arvind / password123     (approves Meera)")
print("MD:          nandita / password123    (top level)")
print("Finance:     ravi / password123       (final verification & payment)")

print("\n=== TEST DATA ===")
print(f"TR-{tr1.id} (Bengaluru, approved) → EC-{claim.id} (draft, 6 items, ₹24,809 net)")
print(f"TR-{tr2.id} (Mumbai, pending)     → waiting for Suresh's approval")
print(f"TR-{tr3.id} (Chennai, pending)    → waiting for Suresh's approval (from Deepa)")
