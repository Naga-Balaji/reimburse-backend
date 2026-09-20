from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('employee', 'Employee'),
        ('manager', 'Manager'),
        ('finance', 'Finance'),
        ('admin', 'Admin'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    department = models.CharField(max_length=100, blank=True)
    reporting_manager = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='subordinates')

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.role})"


class TravelRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='travel_requests')
    destination = models.CharField(max_length=100)
    from_date = models.DateField()
    to_date = models.DateField()
    purpose = models.TextField()
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    advance_requested = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0'))])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Advance disbursement tracking (Finance operations)
    advance_disbursed_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    advance_disbursed_at = models.DateTimeField(null=True, blank=True)
    advance_disbursed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='advances_disbursed')
    advance_disbursement_ref = models.CharField(max_length=100, blank=True, help_text="Finance reference e.g. ADV/2026/0619")

    # Finance review note (when Finance holds back on disbursement without releasing)
    advance_review_note = models.TextField(blank=True, help_text="Finance's reason for holding advance disbursement")
    advance_review_at = models.DateTimeField(null=True, blank=True)
    advance_review_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='advance_reviews')

    # Employee's follow-up when Finance has held their advance
    advance_follow_up_note = models.TextField(blank=True, help_text="Employee's response to Finance's hold")
    advance_follow_up_at = models.DateTimeField(null=True, blank=True)
    advance_follow_up_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='advance_follow_ups')

    @property
    def advance_status(self):
        if not self.advance_requested or self.advance_requested == 0:
            return 'not_requested'
        if self.status != 'approved':
            return 'awaiting_approval'
        if self.advance_disbursed_at:
            return 'disbursed'
        return 'pending_disbursement'

    def __str__(self):
        return f"TR-{self.id} - {self.employee.get_full_name()} to {self.destination}"


class ExpenseClaim(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('paid', 'Paid'),
    ]

    travel_request = models.ForeignKey(TravelRequest, on_delete=models.CASCADE, related_name='expense_claims')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expense_claims')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # AI Insights cache — regenerated only when claim content changes
    ai_insights_data = models.JSONField(null=True, blank=True)
    ai_insights_generated_at = models.DateTimeField(null=True, blank=True)
    ai_insights_content_hash = models.CharField(max_length=64, blank=True)

    def compute_content_hash(self):
        """Hash the fields that influence AI insights — regenerate if this changes."""
        import hashlib, json
        payload = {
            'status': self.status,
            'items': [
                {
                    'cat': item.category,
                    'amt': str(item.amount),
                    'disallowed': str(item.disallowed_amount),
                    'city': item.city or '',
                    'nights': item.nights or 0,
                }
                for item in self.items.all().order_by('id')
            ],
            'estimated': str(self.travel_request.estimated_cost),
            'advance': str(self.travel_request.advance_requested),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def invalidate_ai_cache(self):
        """Called when claim content changes — clears cached insights."""
        self.ai_insights_data = None
        self.ai_insights_generated_at = None
        self.ai_insights_content_hash = ''
        self.save(update_fields=['ai_insights_data', 'ai_insights_generated_at', 'ai_insights_content_hash'])

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"EC-{self.id} - {self.employee.get_full_name()}"

    @property
    def total_claimed(self):
        return sum(item.claimed_amount for item in self.items.all())

    @property
    def total_disallowed(self):
        return sum(item.disallowed_amount for item in self.items.all())

    @property
    def net_reimbursable(self):
        return self.total_claimed - self.total_disallowed

    @property
    def advance_drawn(self):
        """Only counts once Finance has actually disbursed. Zero until then."""
        tr = self.travel_request
        if tr.advance_disbursed_amount is not None:
            return tr.advance_disbursed_amount
        return Decimal('0')

    @property
    def payable_recoverable(self):
        net = self.net_reimbursable
        advance = self.advance_drawn
        return {
            'payable': max(0, net - advance),
            'recoverable': max(0, advance - net)
        }


class ExpenseItem(models.Model):
    CATEGORY_CHOICES = [
        ('lodging', 'Lodging'),
        ('transport', 'Transport'),
        ('meals', 'Meals'),
        ('entertainment', 'Business Entertainment'),
    ]

    TIER1_CITIES = ['Bengaluru', 'Bangalore', 'Mumbai', 'Delhi', 'Hyderabad', 'Chennai', 'Pune', 'Kolkata']
    LODGING_LIMITS = {'tier1': 6000, 'tier2': 4000, 'tier3': 2800}

    claim = models.ForeignKey(ExpenseClaim, on_delete=models.CASCADE, related_name='items')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    description = models.TextField()
    proof_reference = models.CharField(max_length=200, help_text="Email subject, file name, etc.")
    proof_file = models.FileField(upload_to='proofs/', null=True, blank=True, help_text="The actual receipt/invoice/ticket")
    check_in_date = models.DateField(null=True, blank=True, help_text="For lodging only")
    check_out_date = models.DateField(null=True, blank=True, help_text="For lodging only")
    nights = models.IntegerField(null=True, blank=True, help_text="For lodging only")
    city = models.CharField(max_length=100, null=True, blank=True, help_text="For lodging only")
    is_disallowed = models.BooleanField(default=False)
    disallow_reason = models.CharField(max_length=500, blank=True)
    disallowed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    claimed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.get_category_display()} - {self.amount}"

    def apply_policy(self):
        """Compute disallowed and claimed amounts based on policy."""
        # Ensure amount is Decimal
        if not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))

        disallowed = Decimal('0')
        reason = ""

        if self.category == 'lodging' and self.nights and self.city:
            city_lower = self.city.strip()
            if any(city_lower.lower() == c.lower() for c in self.TIER1_CITIES):
                limit = self.LODGING_LIMITS['tier1']
            else:
                limit = self.LODGING_LIMITS['tier3']

            tariff_per_night = self.amount / Decimal(self.nights)
            if tariff_per_night > limit:
                excess_per_night = tariff_per_night - Decimal(str(limit))
                disallowed = excess_per_night * Decimal(self.nights)
                reason = f'Hotel rate ₹{tariff_per_night:.2f}/night exceeds ₹{limit} limit for {self.city}'

        self.disallowed_amount = disallowed
        self.disallow_reason = reason
        self.is_disallowed = disallowed > 0
        self.claimed_amount = self.amount - disallowed

    def save(self, *args, **kwargs):
        self.apply_policy()
        super().save(*args, **kwargs)


from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver([post_save, post_delete], sender='core.ExpenseItem')
def invalidate_ai_insights_on_item_change(sender, instance, **kwargs):
    """When an expense item changes, invalidate the parent claim's AI insights cache."""
    try:
        if instance.claim_id:
            claim = ExpenseClaim.objects.filter(id=instance.claim_id).first()
            if claim and claim.ai_insights_data:
                claim.invalidate_ai_cache()
    except Exception:
        pass


class TRApproval(models.Model):
    """Approval record for a Travel Request. Tiered by estimated cost, mirroring policy §2."""
    LEVEL_CHOICES = [
        ('manager', 'Reporting Manager'),
        ('dept_head', 'Head of Department'),
        ('div_head', 'Head of Division'),
        ('md_ceo', 'MD/CEO'),
    ]
    DECISION_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    travel_request = models.ForeignKey(TravelRequest, on_delete=models.CASCADE, related_name='approvals_chain')
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='tr_approvals_given')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default='pending')
    remarks = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('travel_request', 'level')
        ordering = ['created_at']

    def __str__(self):
        return f'TR-{self.travel_request_id} · {self.get_level_display()} · {self.decision}'


class Approval(models.Model):
    LEVEL_CHOICES = [
        ('manager', 'Reporting Manager'),
        ('dept_head', 'Head of Department'),
        ('div_head', 'Head of Division'),
        ('md_ceo', 'MD/CEO'),
        ('finance', 'Finance'),
    ]

    DECISION_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('returned', 'Returned'),
    ]

    claim = models.ForeignKey(ExpenseClaim, on_delete=models.CASCADE, related_name='approvals')
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='approvals_given')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default='pending')
    remarks = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('claim', 'level')
        ordering = ['created_at']

    def __str__(self):
        return f"{self.claim} - {self.get_level_display()} - {self.decision}"
