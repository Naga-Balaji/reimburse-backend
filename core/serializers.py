from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile, TravelRequest, ExpenseClaim, ExpenseItem, Approval, TRApproval
from decimal import Decimal
from datetime import datetime


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ['user', 'role', 'department', 'reporting_manager']


class TRApprovalSerializer(serializers.ModelSerializer):
    approver_name = serializers.CharField(source='approver.get_full_name', read_only=True, allow_null=True)
    level_display = serializers.CharField(source='get_level_display', read_only=True)

    class Meta:
        model = TRApproval
        fields = ['id', 'level', 'level_display', 'approver', 'approver_name', 'decision', 'remarks', 'decided_at', 'created_at']


class TravelRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.get_full_name', read_only=True)
    days = serializers.SerializerMethodField()
    advance_status = serializers.CharField(read_only=True)
    advance_disbursed_by_name = serializers.CharField(source='advance_disbursed_by.get_full_name', read_only=True, allow_null=True)
    advance_review_by_name = serializers.CharField(source='advance_review_by.get_full_name', read_only=True, allow_null=True)
    advance_follow_up_by_name = serializers.CharField(source='advance_follow_up_by.get_full_name', read_only=True, allow_null=True)
    approvals_chain = TRApprovalSerializer(many=True, read_only=True)
    related_claim_id = serializers.SerializerMethodField()
    pending_action_from_me = serializers.SerializerMethodField()

    def get_related_claim_id(self, obj):
        claim = obj.expense_claims.first()
        return claim.id if claim else None

    def get_pending_action_from_me(self, obj):
        """True if the current user is the next-in-line approver whose slot is still pending."""
        request = self.context.get('request')
        if not request or obj.status != 'pending':
            return False
        # Import here to avoid circular
        from .views import _tr_get_user_level
        my_level = _tr_get_user_level(request.user, obj)
        if not my_level:
            return False
        my_slot = obj.approvals_chain.filter(level=my_level).first()
        return bool(my_slot and my_slot.decision == 'pending')

    class Meta:
        model = TravelRequest
        fields = [
            'id', 'employee', 'employee_name', 'destination', 'from_date', 'to_date', 'days',
            'purpose', 'estimated_cost', 'advance_requested', 'status', 'created_at',
            'advance_status', 'advance_disbursed_amount', 'advance_disbursed_at',
            'advance_disbursed_by', 'advance_disbursed_by_name', 'advance_disbursement_ref',
            'advance_review_note', 'advance_review_at', 'advance_review_by', 'advance_review_by_name',
            'advance_follow_up_note', 'advance_follow_up_at', 'advance_follow_up_by', 'advance_follow_up_by_name',
            'approvals_chain', 'related_claim_id', 'pending_action_from_me',
        ]
        read_only_fields = ['id', 'created_at', 'employee', 'advance_disbursed_by', 'advance_disbursed_at', 'advance_review_at', 'advance_review_by']

    def get_days(self, obj):
        delta = obj.to_date - obj.from_date
        return delta.days + 1


class ExpenseItemSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    proof_file_url = serializers.SerializerMethodField()
    proof_file_name = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseItem
        fields = [
            'id', 'claim', 'category', 'category_display', 'amount', 'description',
            'proof_reference', 'proof_file', 'proof_file_url', 'proof_file_name',
            'check_in_date', 'check_out_date', 'nights', 'city',
            'is_disallowed', 'disallow_reason', 'disallowed_amount', 'claimed_amount'
        ]
        read_only_fields = ['id', 'is_disallowed', 'disallow_reason', 'disallowed_amount', 'claimed_amount', 'proof_file_url', 'proof_file_name']

    def get_proof_file_url(self, obj):
        if obj.proof_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.proof_file.url)
            return obj.proof_file.url
        return None

    def get_proof_file_name(self, obj):
        if obj.proof_file:
            import os
            return os.path.basename(obj.proof_file.name)
        return None

    def validate(self, data):
        category = data.get('category')
        amount = data.get('amount')

        # Validate lodging
        if category == 'lodging':
            if not data.get('check_in_date') or not data.get('check_out_date'):
                raise serializers.ValidationError("Check-in and check-out dates required for lodging")
            if not data.get('city'):
                raise serializers.ValidationError("City required for lodging")
            if not data.get('nights') or data.get('nights') <= 0:
                raise serializers.ValidationError("Number of nights must be greater than 0")

        return data

    def create(self, validated_data):
        item = ExpenseItem.objects.create(**validated_data)
        self._validate_and_set_disallowed(item)
        return item

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        self._validate_and_set_disallowed(instance)
        return instance

    def _validate_and_set_disallowed(self, item):
        """Validate item against policy and mark disallowed if needed"""
        disallowed_amount = Decimal('0')
        disallow_reason = ""
        claimed_amount = item.amount

        if item.category == 'lodging':
            disallowed = self._validate_lodging(item)
            if disallowed['is_disallowed']:
                disallowed_amount = disallowed['disallowed_amount']
                disallow_reason = disallowed['reason']
                claimed_amount = item.amount - disallowed_amount

        item.is_disallowed = disallowed_amount > 0
        item.disallowed_amount = disallowed_amount
        item.claimed_amount = claimed_amount
        item.disallow_reason = disallow_reason
        item.save()

    def _validate_lodging(self, item):
        """Validate lodging against policy limits"""
        limits = {
            'Bengaluru': 6000,
            'Mumbai': 6000,
            'Delhi': 6000,
            'Hyderabad': 6000,
            'Chennai': 6000,
            'Pune': 6000,
            'Kolkata': 6000,
        }
        default_limit = 2800

        city = item.city
        limit = limits.get(city, default_limit)

        tariff_per_night = item.amount / item.nights if item.nights else 0
        excess_per_night = max(0, tariff_per_night - limit)
        disallowed_amount = excess_per_night * item.nights

        if disallowed_amount > 0:
            return {
                'is_disallowed': True,
                'disallowed_amount': disallowed_amount,
                'reason': f'Hotel rate ₹{tariff_per_night:.2f}/night exceeds limit ₹{limit} for {city}. Excess: ₹{disallowed_amount:.2f}'
            }

        return {'is_disallowed': False, 'disallowed_amount': 0, 'reason': ''}


class ExpenseClaimSerializer(serializers.ModelSerializer):
    items = ExpenseItemSerializer(many=True, read_only=True)
    employee_name = serializers.CharField(source='employee.get_full_name', read_only=True)
    travel_destination = serializers.CharField(source='travel_request.destination', read_only=True)
    total_claimed = serializers.SerializerMethodField()
    total_disallowed = serializers.SerializerMethodField()
    net_reimbursable = serializers.SerializerMethodField()
    advance_drawn = serializers.SerializerMethodField()
    payable_recoverable = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()
    travel_request_detail = serializers.SerializerMethodField()
    pending_action_from_me = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseClaim
        fields = [
            'id', 'travel_request', 'travel_request_detail', 'employee', 'employee_name', 'travel_destination',
            'status', 'items', 'total_claimed', 'total_disallowed', 'net_reimbursable',
            'advance_drawn', 'payable_recoverable', 'approvals', 'submitted_at', 'created_at',
            'pending_action_from_me',
        ]
        read_only_fields = ['id', 'created_at', 'employee']

    def get_pending_action_from_me(self, obj):
        """True if the current user is the next-in-line approver whose slot is still pending."""
        request = self.context.get('request')
        if not request or obj.status not in ('submitted', 'approved'):
            return False
        from .views import ExpenseClaimViewSet
        try:
            viewset = ExpenseClaimViewSet()
            my_level = viewset._get_approval_level(request.user, obj)
        except Exception:
            return False
        if not my_level:
            return False
        # Finance approves 'finance' level only when claim is fully approved
        if my_level == 'finance' and obj.status != 'approved':
            return False
        my_slot = obj.approvals.filter(level=my_level).first()
        return bool(my_slot and my_slot.decision == 'pending')

    def get_travel_request_detail(self, obj):
        tr = obj.travel_request
        return {
            'id': tr.id,
            'destination': tr.destination,
            'from_date': tr.from_date.isoformat(),
            'to_date': tr.to_date.isoformat(),
            'estimated_cost': float(tr.estimated_cost),
            'advance_requested': float(tr.advance_requested),
            'advance_status': tr.advance_status,
            'advance_disbursed_amount': float(tr.advance_disbursed_amount) if tr.advance_disbursed_amount is not None else None,
            'advance_disbursed_at': tr.advance_disbursed_at.isoformat() if tr.advance_disbursed_at else None,
            'advance_disbursed_by_name': tr.advance_disbursed_by.get_full_name() if tr.advance_disbursed_by else None,
            'advance_disbursement_ref': tr.advance_disbursement_ref,
            # Finance hold + employee follow-up thread
            'advance_review_note': tr.advance_review_note,
            'advance_review_at': tr.advance_review_at.isoformat() if tr.advance_review_at else None,
            'advance_review_by_name': tr.advance_review_by.get_full_name() if tr.advance_review_by else None,
            'advance_follow_up_note': tr.advance_follow_up_note,
            'advance_follow_up_at': tr.advance_follow_up_at.isoformat() if tr.advance_follow_up_at else None,
            'advance_follow_up_by_name': tr.advance_follow_up_by.get_full_name() if tr.advance_follow_up_by else None,
        }

    def get_total_claimed(self, obj):
        return sum(item.claimed_amount for item in obj.items.all())

    def get_total_disallowed(self, obj):
        return sum(item.disallowed_amount for item in obj.items.all())

    def get_net_reimbursable(self, obj):
        return self.get_total_claimed(obj) - self.get_total_disallowed(obj)

    def get_advance_drawn(self, obj):
        # Use the model property — it correctly returns 0 until Finance actually disburses
        return obj.advance_drawn

    def get_payable_recoverable(self, obj):
        net = self.get_net_reimbursable(obj)
        advance = self.get_advance_drawn(obj)
        return {
            'payable': max(0, net - advance),
            'recoverable': max(0, advance - net)
        }

    def get_approvals(self, obj):
        approvals = obj.approvals.all()
        return ApprovalSerializer(approvals, many=True).data


class ApprovalSerializer(serializers.ModelSerializer):
    approver_name = serializers.CharField(source='approver.get_full_name', read_only=True, allow_null=True)
    level_display = serializers.CharField(source='get_level_display', read_only=True)

    class Meta:
        model = Approval
        fields = ['id', 'claim', 'level', 'level_display', 'approver', 'approver_name', 'decision', 'remarks', 'decided_at', 'created_at']
        read_only_fields = ['id', 'claim', 'level', 'approver', 'created_at']
