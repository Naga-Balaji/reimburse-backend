from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime
from decimal import Decimal
from .models import UserProfile, TravelRequest, ExpenseClaim, ExpenseItem, Approval, TRApproval
from .serializers import (
    UserSerializer, UserProfileSerializer, TravelRequestSerializer,
    ExpenseClaimSerializer, ExpenseItemSerializer, ApprovalSerializer
)
from .parsers import parse_eml_content, deduplicate_parsed
from .llm import generate_ai_insights, llm_parse_email


class IsEmployee(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsManager(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            return request.user.profile.role in ['manager', 'admin']
        except:
            return False


class IsFinance(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            return request.user.profile.role in ['finance', 'admin']
        except:
            return False


def _tr_required_levels(amount):
    """Approval levels required for a TR of the given estimated amount (policy §2)."""
    if amount <= 25000:
        return ['manager']
    elif amount <= 75000:
        return ['manager', 'dept_head']
    elif amount <= 200000:
        return ['manager', 'dept_head', 'div_head']
    return ['manager', 'dept_head', 'div_head', 'md_ceo']


def _tr_get_user_level(user, tr):
    """Return which approval level `user` handles for `tr`, or None if not an approver."""
    try:
        profile = user.profile
        if profile.role not in ['manager', 'admin']:
            return None
        # Direct manager?
        if tr.employee.profile.reporting_manager_id == user.id:
            return 'manager'
        # Manager of employee's manager (HoD)?
        emp_mgr = tr.employee.profile.reporting_manager
        if emp_mgr and emp_mgr.profile.reporting_manager_id == user.id:
            return 'dept_head'
        # One more up (Div Head)?
        if emp_mgr and emp_mgr.profile.reporting_manager and emp_mgr.profile.reporting_manager.profile.reporting_manager_id == user.id:
            return 'div_head'
        # Top level
        if profile.role == 'admin':
            return 'md_ceo'
    except Exception:
        return None
    return None


class UserProfileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [IsEmployee]

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user's profile"""
        try:
            profile = request.user.profile
            serializer = self.get_serializer(profile)
            return Response(serializer.data)
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)


class TravelRequestViewSet(viewsets.ModelViewSet):
    serializer_class = TravelRequestSerializer
    permission_classes = [IsEmployee]

    def get_queryset(self):
        user = self.request.user
        try:
            role = user.profile.role
            if role == 'admin' or role == 'finance':
                return TravelRequest.objects.all()
            elif role == 'manager':
                # Manager sees own + direct + indirect reports (their subordinates' teams)
                own = TravelRequest.objects.filter(employee=user)
                direct = TravelRequest.objects.filter(employee__profile__reporting_manager=user)
                subordinate_managers = User.objects.filter(profile__reporting_manager=user)
                indirect = TravelRequest.objects.filter(employee__profile__reporting_manager__in=subordinate_managers)
                return (own | direct | indirect).distinct()
            else:
                return TravelRequest.objects.filter(employee=user)
        except:
            return TravelRequest.objects.filter(employee=user)

    def perform_create(self, serializer):
        tr = serializer.save(employee=self.request.user)
        # Auto-create tiered approval records based on estimated cost (policy §2)
        levels = _tr_required_levels(float(tr.estimated_cost))
        for lvl in levels:
            TRApproval.objects.get_or_create(travel_request=tr, level=lvl)

    @action(detail=True, methods=['post'], permission_classes=[IsManager])
    def approve(self, request, pk=None):
        travel_request = self.get_object()
        remarks = request.data.get('remarks', '')
        user = request.user

        # Determine the user's approval level for this TR
        my_level = _tr_get_user_level(user, travel_request)
        if not my_level:
            return Response({'error': 'You are not an approver for this travel request'}, status=status.HTTP_403_FORBIDDEN)

        try:
            appr = travel_request.approvals_chain.get(level=my_level)
        except TRApproval.DoesNotExist:
            return Response({'error': f'No {my_level} approval slot exists'}, status=status.HTTP_400_BAD_REQUEST)

        # Enforce sequential: previous levels must be approved
        required = _tr_required_levels(float(travel_request.estimated_cost))
        my_idx = required.index(my_level)
        for prior in required[:my_idx]:
            prev = travel_request.approvals_chain.filter(level=prior).first()
            if not prev or prev.decision != 'approved':
                return Response({'error': f'Previous level ({prior}) must approve first'}, status=status.HTTP_400_BAD_REQUEST)

        appr.decision = 'approved'
        appr.approver = user
        appr.remarks = remarks
        appr.decided_at = timezone.now()
        appr.save()

        # If all levels approved, mark TR approved
        if all(a.decision == 'approved' for a in travel_request.approvals_chain.all()):
            travel_request.status = 'approved'
            travel_request.save(update_fields=['status'])

        return Response(TravelRequestSerializer(travel_request, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsManager])
    def reject(self, request, pk=None):
        travel_request = self.get_object()
        remarks = request.data.get('remarks', '')
        user = request.user

        my_level = _tr_get_user_level(user, travel_request)
        if not my_level:
            return Response({'error': 'You are not an approver for this travel request'}, status=status.HTTP_403_FORBIDDEN)

        try:
            appr = travel_request.approvals_chain.get(level=my_level)
        except TRApproval.DoesNotExist:
            return Response({'error': 'No approval slot'}, status=status.HTTP_400_BAD_REQUEST)

        appr.decision = 'rejected'
        appr.approver = user
        appr.remarks = remarks
        appr.decided_at = timezone.now()
        appr.save()

        travel_request.status = 'rejected'
        travel_request.save(update_fields=['status'])
        return Response(TravelRequestSerializer(travel_request, context={'request': request}).data)

    @action(detail=True, methods=['get'], permission_classes=[IsFinance])
    def advance_context(self, request, pk=None):
        """Full context for Finance to review before disbursing an advance."""
        tr = self.get_object()
        emp = tr.employee

        # Outstanding advances: disbursed but claim not yet paid
        outstanding_qs = TravelRequest.objects.filter(
            employee=emp,
            advance_disbursed_at__isnull=False,
        ).exclude(id=tr.id)
        outstanding_list = []
        outstanding_total = Decimal('0')
        for ot in outstanding_qs:
            claim = ot.expense_claims.first()
            if claim and claim.status != 'paid':
                outstanding_list.append({
                    'tr_id': ot.id,
                    'destination': ot.destination,
                    'from_date': ot.from_date.isoformat(),
                    'to_date': ot.to_date.isoformat(),
                    'advance_amount': float(ot.advance_disbursed_amount or ot.advance_requested),
                    'disbursed_at': ot.advance_disbursed_at.isoformat(),
                    'reference': ot.advance_disbursement_ref,
                    'claim_status': claim.status if claim else 'no_claim',
                    'days_outstanding': (timezone.now().date() - ot.advance_disbursed_at.date()).days,
                })
                outstanding_total += ot.advance_disbursed_amount or ot.advance_requested

        # History: past disbursements that have been settled
        history_qs = TravelRequest.objects.filter(
            employee=emp,
            advance_disbursed_at__isnull=False,
            expense_claims__status='paid',
        ).exclude(id=tr.id).distinct().order_by('-advance_disbursed_at')[:5]
        history = []
        for ht in history_qs:
            claim = ht.expense_claims.filter(status='paid').first()
            if not claim:
                continue
            adv = float(ht.advance_disbursed_amount or ht.advance_requested)
            net = float(claim.net_reimbursable)
            history.append({
                'tr_id': ht.id,
                'destination': ht.destination,
                'advance': adv,
                'actual_net': net,
                'variance_pct': ((net - adv) / adv * 100) if adv > 0 else 0,
                'settled_on': claim.updated_at.isoformat() if claim else None,
            })

        # Policy check: 60% cap
        max_allowed = float(tr.estimated_cost) * 0.60
        within_cap = float(tr.advance_requested) <= max_allowed

        try:
            profile = emp.profile
            department = profile.department
            reporting_manager = profile.reporting_manager.get_full_name() if profile.reporting_manager else None
        except:
            department = ''
            reporting_manager = None

        return Response({
            'travel_request': {
                'id': tr.id,
                'destination': tr.destination,
                'from_date': tr.from_date.isoformat(),
                'to_date': tr.to_date.isoformat(),
                'days': (tr.to_date - tr.from_date).days + 1,
                'purpose': tr.purpose,
                'estimated_cost': float(tr.estimated_cost),
                'advance_requested': float(tr.advance_requested),
                'status': tr.status,
                'created_at': tr.created_at.isoformat(),
                'advance_review_note': tr.advance_review_note,
                'advance_review_at': tr.advance_review_at.isoformat() if tr.advance_review_at else None,
                'advance_review_by_name': tr.advance_review_by.get_full_name() if tr.advance_review_by else None,
                'advance_follow_up_note': tr.advance_follow_up_note,
                'advance_follow_up_at': tr.advance_follow_up_at.isoformat() if tr.advance_follow_up_at else None,
                'advance_follow_up_by_name': tr.advance_follow_up_by.get_full_name() if tr.advance_follow_up_by else None,
            },
            'employee': {
                'name': emp.get_full_name(),
                'username': emp.username,
                'email': emp.email,
                'department': department,
                'reporting_manager': reporting_manager,
            },
            'outstanding': {
                'count': len(outstanding_list),
                'total_amount': float(outstanding_total),
                'list': outstanding_list,
            },
            'history': {
                'count': len(history),
                'total_disbursed': sum(h['advance'] for h in history),
                'avg_variance_pct': (sum(h['variance_pct'] for h in history) / len(history)) if history else 0,
                'list': history,
            },
            'policy': {
                'max_allowed_60pct': max_allowed,
                'requested_within_cap': within_cap,
                'excess_amount': max(0, float(tr.advance_requested) - max_allowed),
            },
        })

    @action(detail=True, methods=['post'], permission_classes=[IsEmployee])
    def follow_up_advance(self, request, pk=None):
        """Employee posts a follow-up note in response to Finance's hold."""
        travel_request = self.get_object()
        note = (request.data.get('note') or '').strip()

        if not note:
            return Response({'error': 'Follow-up note cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)
        if travel_request.employee != request.user:
            return Response({'error': 'Only the employee who raised this TR can follow up'}, status=status.HTTP_403_FORBIDDEN)
        if not travel_request.advance_review_note:
            return Response({'error': 'No Finance hold to follow up on'}, status=status.HTTP_400_BAD_REQUEST)
        if travel_request.advance_disbursed_at:
            return Response({'error': 'Advance already disbursed — no follow-up needed'}, status=status.HTTP_400_BAD_REQUEST)

        travel_request.advance_follow_up_note = note
        travel_request.advance_follow_up_at = timezone.now()
        travel_request.advance_follow_up_by = request.user
        travel_request.save(update_fields=['advance_follow_up_note', 'advance_follow_up_at', 'advance_follow_up_by'])

        serializer = self.get_serializer(travel_request)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsFinance])
    def hold_advance(self, request, pk=None):
        """Finance defers/holds the disbursement without releasing it. Optional review note."""
        travel_request = self.get_object()
        note = (request.data.get('note') or '').strip()

        if travel_request.advance_disbursed_at:
            return Response({'error': 'Advance already disbursed — cannot hold'}, status=status.HTTP_400_BAD_REQUEST)

        travel_request.advance_review_note = note
        travel_request.advance_review_at = timezone.now()
        travel_request.advance_review_by = request.user
        travel_request.save(update_fields=['advance_review_note', 'advance_review_at', 'advance_review_by'])

        serializer = self.get_serializer(travel_request)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsFinance])
    def disburse_advance(self, request, pk=None):
        """Finance disburses the advance. Distinct from claim payment."""
        travel_request = self.get_object()

        if travel_request.status != 'approved':
            return Response({'error': 'Travel request must be approved before advance disbursement'}, status=status.HTTP_400_BAD_REQUEST)
        if travel_request.advance_requested == 0:
            return Response({'error': 'No advance was requested for this travel'}, status=status.HTTP_400_BAD_REQUEST)
        if travel_request.advance_disbursed_at:
            return Response({'error': 'Advance already disbursed'}, status=status.HTTP_400_BAD_REQUEST)

        # Amount may be adjusted by Finance (defaults to requested)
        amount = request.data.get('amount', travel_request.advance_requested)
        ref = request.data.get('reference', f'ADV/{timezone.now().year}/{travel_request.id:04d}')

        travel_request.advance_disbursed_amount = Decimal(str(amount))
        travel_request.advance_disbursed_at = timezone.now()
        travel_request.advance_disbursed_by = request.user
        travel_request.advance_disbursement_ref = ref
        travel_request.save()

        serializer = self.get_serializer(travel_request)
        return Response(serializer.data)


class ExpenseItemViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseItemSerializer
    permission_classes = [IsEmployee]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        user = self.request.user
        qs = ExpenseItem.objects.all()
        claim_id = self.request.query_params.get('claim_id')
        if claim_id:
            qs = qs.filter(claim_id=claim_id)
        # Restrict to items in claims user can access
        try:
            role = user.profile.role
            if role in ['admin', 'finance']:
                return qs
            elif role == 'manager':
                return qs.filter(claim__employee__profile__reporting_manager=user) | qs.filter(claim__employee=user)
            else:
                return qs.filter(claim__employee=user)
        except:
            return qs.filter(claim__employee=user)

    def perform_create(self, serializer):
        serializer.save()


class ApprovalWorkflowHelper:
    """Helper to determine approval levels required"""

    @staticmethod
    def get_required_approval_levels(amount):
        """Based on net reimbursable amount, return list of approval levels"""
        if amount <= 25000:
            return ['manager', 'finance']
        elif amount <= 75000:
            return ['manager', 'dept_head', 'finance']
        elif amount <= 200000:
            return ['manager', 'dept_head', 'div_head', 'finance']
        else:
            return ['manager', 'dept_head', 'div_head', 'md_ceo', 'finance']

    @staticmethod
    def create_approval_workflow(claim):
        """Create approval records for the claim"""
        net_amount = claim.net_reimbursable
        levels = ApprovalWorkflowHelper.get_required_approval_levels(float(net_amount))

        for level in levels:
            Approval.objects.get_or_create(claim=claim, level=level)


class ExpenseClaimViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseClaimSerializer
    permission_classes = [IsEmployee]

    def get_queryset(self):
        user = self.request.user
        try:
            role = user.profile.role
            if role == 'admin':
                return ExpenseClaim.objects.all()
            elif role == 'finance':
                # Finance only sees claims where all business approvals are done (or already paid)
                return ExpenseClaim.objects.filter(status__in=['approved', 'paid', 'rejected'])
            elif role == 'manager':
                # Manager sees own + direct reports + indirect reports (subordinate-managers' teams)
                own_claims = ExpenseClaim.objects.filter(employee=user)
                direct_reports = ExpenseClaim.objects.filter(
                    employee__profile__reporting_manager=user
                ).exclude(status='draft')
                # If I'm HoD/Div Head, my subordinates are also managers with their own teams
                subordinate_managers = User.objects.filter(profile__reporting_manager=user)
                indirect_reports = ExpenseClaim.objects.filter(
                    employee__profile__reporting_manager__in=subordinate_managers
                ).exclude(status='draft')
                return (own_claims | direct_reports | indirect_reports).distinct()
            else:
                return ExpenseClaim.objects.filter(employee=user)
        except:
            return ExpenseClaim.objects.filter(employee=user)

    def perform_create(self, serializer):
        serializer.save(employee=self.request.user)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit claim for approval"""
        claim = self.get_object()

        # Check if user is the employee
        if claim.employee != request.user:
            return Response({'error': 'Cannot submit another user\'s claim'}, status=status.HTTP_403_FORBIDDEN)

        if claim.status != 'draft':
            return Response({'error': 'Claim can only be submitted from draft status'}, status=status.HTTP_400_BAD_REQUEST)

        if not claim.items.exists():
            return Response({'error': 'Claim must have at least one expense item'}, status=status.HTTP_400_BAD_REQUEST)

        claim.status = 'submitted'
        claim.submitted_at = timezone.now()
        claim.save()

        # Create approval workflow
        ApprovalWorkflowHelper.create_approval_workflow(claim)

        serializer = self.get_serializer(claim)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsManager])
    def approve(self, request, pk=None):
        """Manager/Finance approves the claim"""
        claim = self.get_object()
        remarks = request.data.get('remarks', '')

        if claim.status not in ['submitted', 'approved']:
            return Response({'error': 'Claim cannot be approved in current status'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            approver_profile = request.user.profile
            user_level = self._get_approval_level(request.user, claim)

            # Update the approval record
            approval = Approval.objects.get(claim=claim, level=user_level)
            approval.decision = 'approved'
            approval.remarks = remarks
            approval.approver = request.user
            approval.decided_at = timezone.now()
            approval.save()

            # Check if all approvals before finance are complete
            all_approvals = claim.approvals.all()
            finance_approval = all_approvals.filter(level='finance').first()

            if self._are_all_non_finance_approvals_done(claim):
                claim.status = 'approved'
                claim.save()

            serializer = self.get_serializer(claim)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Approval.DoesNotExist:
            return Response({'error': 'Approval record not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsManager])
    def reject(self, request, pk=None):
        """Manager/Finance rejects the claim"""
        claim = self.get_object()
        remarks = request.data.get('remarks', '')

        if claim.status not in ['submitted', 'approved']:
            return Response({'error': 'Claim cannot be rejected in current status'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_level = self._get_approval_level(request.user, claim)

            approval = Approval.objects.get(claim=claim, level=user_level)
            approval.decision = 'rejected'
            approval.remarks = remarks
            approval.approver = request.user
            approval.decided_at = timezone.now()
            approval.save()

            claim.status = 'rejected'
            claim.save()

            serializer = self.get_serializer(claim)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Approval.DoesNotExist:
            return Response({'error': 'Approval record not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsManager])
    def return_claim(self, request, pk=None):
        """Manager returns claim for corrections"""
        claim = self.get_object()
        remarks = request.data.get('remarks', '')

        try:
            user_level = self._get_approval_level(request.user, claim)

            approval = Approval.objects.get(claim=claim, level=user_level)
            approval.decision = 'returned'
            approval.remarks = remarks
            approval.approver = request.user
            approval.decided_at = timezone.now()
            approval.save()

            claim.status = 'draft'
            claim.save()

            # Reset all approvals
            claim.approvals.all().update(decision='pending', approver=None, decided_at=None)

            serializer = self.get_serializer(claim)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Approval.DoesNotExist:
            return Response({'error': 'Approval record not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsFinance])
    def verify_and_pay(self, request, pk=None):
        """Finance verifies and releases payment"""
        claim = self.get_object()
        remarks = request.data.get('remarks', '')

        if claim.status not in ['approved', 'submitted']:
            return Response({'error': 'Claim must be approved before payment'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            approval = Approval.objects.get(claim=claim, level='finance')
            approval.decision = 'approved'
            approval.remarks = remarks
            approval.approver = request.user
            approval.decided_at = timezone.now()
            approval.save()

            claim.status = 'paid'
            claim.save()

            serializer = self.get_serializer(claim)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Approval.DoesNotExist:
            return Response({'error': 'Finance approval not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _get_approval_level(self, user, claim):
        """Determine the approval level for this user"""
        try:
            profile = user.profile
            if profile.role == 'finance':
                return 'finance'
            elif profile.role in ['manager', 'admin']:
                # Check if user is a manager
                if claim.employee.profile.reporting_manager == user:
                    return 'manager'
                # Check if user is a dept head
                dept = claim.employee.profile.department
                if profile.department == dept and profile.role in ['manager', 'admin']:
                    return 'dept_head'
                return 'manager'
        except:
            pass
        return 'manager'

    def _are_all_non_finance_approvals_done(self, claim):
        """Check if all non-finance approvals are complete"""
        approvals = claim.approvals.exclude(level='finance')
        return all(a.decision == 'approved' for a in approvals)

    @action(detail=True, methods=['get'], permission_classes=[IsEmployee])
    def employee_context(self, request, pk=None):
        """Context about the claimant for approvers: past claims, spending patterns, department info."""
        claim = self.get_object()
        try:
            role = request.user.profile.role
            if role not in ['manager', 'finance', 'admin']:
                return Response({'error': 'Employee context available for approvers only'}, status=status.HTTP_403_FORBIDDEN)
        except:
            return Response({'error': 'Profile not found'}, status=status.HTTP_403_FORBIDDEN)

        employee = claim.employee
        past_claims = ExpenseClaim.objects.filter(
            employee=employee,
            status__in=['approved', 'paid', 'rejected']
        ).exclude(id=claim.id).order_by('-created_at')

        past_data = []
        total_approved = 0
        total_disallowed = 0
        for pc in past_claims[:10]:
            net = float(pc.net_reimbursable)
            disallowed = float(pc.total_disallowed)
            past_data.append({
                'id': pc.id,
                'destination': pc.travel_request.destination,
                'from_date': pc.travel_request.from_date.isoformat(),
                'to_date': pc.travel_request.to_date.isoformat(),
                'nights': (pc.travel_request.to_date - pc.travel_request.from_date).days,
                'net_reimbursable': net,
                'disallowed': disallowed,
                'status': pc.status,
                'created_at': pc.created_at.isoformat(),
            })
            if pc.status in ['approved', 'paid']:
                total_approved += net
                total_disallowed += disallowed

        # Pending travel requests
        pending_trs = TravelRequest.objects.filter(
            employee=employee, status='pending'
        ).count()

        # Category breakdown from past claims
        from collections import defaultdict
        cat_breakdown = defaultdict(float)
        for pc in past_claims:
            for item in pc.items.all():
                cat_breakdown[item.category] += float(item.claimed_amount)

        try:
            profile = employee.profile
            department = profile.department
            reporting_manager = profile.reporting_manager.get_full_name() if profile.reporting_manager else None
        except:
            department = ''
            reporting_manager = None

        # Trip-approval context: what did we approve at TR time vs actual claim
        tr = claim.travel_request
        estimated = float(tr.estimated_cost)
        actual_net = float(claim.net_reimbursable)
        deviation_pct = ((actual_net - estimated) / estimated * 100) if estimated > 0 else 0

        return Response({
            'employee': {
                'name': employee.get_full_name(),
                'email': employee.email,
                'department': department,
                'reporting_manager': reporting_manager,
            },
            'stats': {
                'total_past_claims': past_claims.count(),
                'total_approved_amount': total_approved,
                'total_disallowed_amount': total_disallowed,
                'disallow_rate': (total_disallowed / (total_approved + total_disallowed) * 100) if (total_approved + total_disallowed) > 0 else 0,
                'pending_travel_requests': pending_trs,
                'category_breakdown': dict(cat_breakdown),
            },
            'past_claims': past_data,
            'current_trip': {
                'tr_id': tr.id,
                'destination': tr.destination,
                'from_date': tr.from_date.isoformat(),
                'to_date': tr.to_date.isoformat(),
                'purpose': tr.purpose,
                'estimated_cost': estimated,
                'advance_drawn': float(tr.advance_requested),
                'actual_net': actual_net,
                'deviation_amount': actual_net - estimated,
                'deviation_pct': deviation_pct,
                'tr_status': tr.status,
                'tr_created_at': tr.created_at.isoformat(),
            },
        })

    @action(detail=True, methods=['get', 'post'], permission_classes=[IsEmployee])
    def ai_insights(self, request, pk=None):
        """
        Get or regenerate AI-powered verification insights for approvers.
        GET: returns cached insights if fresh, else generates and caches.
        POST: forces regeneration (bypasses cache).
        """
        claim = self.get_object()
        try:
            role = request.user.profile.role
            if role not in ['manager', 'finance', 'admin']:
                return Response({'error': 'AI insights available for approvers only'}, status=status.HTTP_403_FORBIDDEN)
        except:
            return Response({'error': 'Profile not found'}, status=status.HTTP_403_FORBIDDEN)

        force_refresh = request.method == 'POST'
        current_hash = claim.compute_content_hash()

        # Return cached insights if fresh and not forcing refresh
        if not force_refresh and claim.ai_insights_data and claim.ai_insights_content_hash == current_hash:
            cached = dict(claim.ai_insights_data)
            cached['_cached'] = True
            cached['_generated_at'] = claim.ai_insights_generated_at.isoformat() if claim.ai_insights_generated_at else None
            return Response(cached)

        # Otherwise generate fresh
        insights = generate_ai_insights(claim)
        if insights and 'error' not in insights:
            claim.ai_insights_data = insights
            claim.ai_insights_generated_at = timezone.now()
            claim.ai_insights_content_hash = current_hash
            claim.save(update_fields=['ai_insights_data', 'ai_insights_generated_at', 'ai_insights_content_hash'])
            insights['_cached'] = False
            insights['_generated_at'] = claim.ai_insights_generated_at.isoformat()
        return Response(insights)


# ─────────────────────────────────────────────
# Email import endpoint
# ─────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsEmployee])
def import_emails(request):
    """
    Parse uploaded .eml files or raw email text.
    Returns structured results with parser attribution and dedup flags.

    Body:
      {
        "emails": [
          {"filename": "01_...", "content": "<raw eml text>"}
        ],
        "use_llm_fallback": true|false
      }
    """
    emails = request.data.get('emails', [])
    use_llm = request.data.get('use_llm_fallback', True)

    employee_first_name = request.user.first_name or request.user.username

    parsed_all = []
    for e in emails:
        content = e.get('content', '')
        filename = e.get('filename', 'unnamed.eml')
        try:
            result = parse_eml_content(content, employee_first_name=employee_first_name)
            result['filename'] = filename
            # If no pattern parser matched and body is not too small, try LLM
            if result['parsed'] is None and use_llm and len(content) > 100:
                subj = result['subject']
                from_a = result['from']
                body = content  # give LLM the full email including headers
                llm_result = llm_parse_email(subj, from_a, body)
                if llm_result and 'error' not in llm_result:
                    result['parsed'] = llm_result
                    result['parser'] = 'llm_fallback'
                elif llm_result and 'error' in llm_result:
                    result['parsed'] = {'kind': 'unclear', 'reason': llm_result.get('message', 'LLM unavailable')}
                    result['parser'] = 'llm_error'
            parsed_all.append(result)
        except Exception as ex:
            parsed_all.append({
                'filename': filename,
                'error': str(ex),
                'parsed': None,
            })

    # Deduplicate
    parsed_all = deduplicate_parsed(parsed_all)

    # Summary
    def kind_of(p):
        return (p.get('parsed') or {}).get('kind')
    summary = {
        'total_emails': len(parsed_all),
        'expenses_found': sum(1 for p in parsed_all if kind_of(p) == 'expense'),
        'lodging_found': sum(1 for p in parsed_all if kind_of(p) == 'lodging_invoice'),
        'noise_filtered': sum(1 for p in parsed_all if kind_of(p) == 'noise'),
        'info_only': sum(1 for p in parsed_all if kind_of(p) == 'info_only'),
        'unclear': sum(1 for p in parsed_all if kind_of(p) == 'unclear'),
        'unparseable': sum(1 for p in parsed_all if p.get('parsed') is None),
    }

    return Response({
        'items': parsed_all,
        'summary': summary,
    })


@api_view(['POST'])
@permission_classes([IsEmployee])
def create_items_from_import(request):
    """
    Create ExpenseItem records from selected parsed results.

    Body:
      {
        "claim_id": <int>,
        "items": [
          {"category": "transport", "amount": ..., "description": "...", "proof_reference": "..."},
          {"category": "lodging", "amount": ..., "check_in_date": "...", ...}
        ]
      }
    """
    claim_id = request.data.get('claim_id')
    items = request.data.get('items', [])

    try:
        claim = ExpenseClaim.objects.get(id=claim_id, employee=request.user)
    except ExpenseClaim.DoesNotExist:
        return Response({'error': 'Claim not found'}, status=status.HTTP_404_NOT_FOUND)

    if claim.status != 'draft':
        return Response({'error': 'Can only add items to a draft claim'}, status=status.HTTP_400_BAD_REQUEST)

    created = []
    for it in items:
        try:
            category = it.get('category', 'transport')
            # Special handling for lodging: split room charges from GST
            # so per-night limit only applies to the tariff, not the GST
            if category == 'lodging' and it.get('gst_amount') and it.get('room_charges'):
                room = ExpenseItem(
                    claim=claim,
                    category='lodging',
                    amount=Decimal(str(it['room_charges'])),
                    description=it.get('description', '') + ' — Room charges',
                    proof_reference=it.get('proof_reference', ''),
                    check_in_date=it.get('check_in_date') or None,
                    check_out_date=it.get('check_out_date') or None,
                    nights=it.get('nights') or None,
                    city=it.get('city') or None,
                )
                room.save()
                gst = ExpenseItem(
                    claim=claim,
                    category='lodging',
                    amount=Decimal(str(it['gst_amount'])),
                    description=it.get('description', '') + ' — GST on room',
                    proof_reference=it.get('proof_reference', ''),
                )
                gst.save()
                created.append({'id': room.id, 'category': 'lodging', 'amount': float(room.amount), 'note': 'room'})
                created.append({'id': gst.id, 'category': 'lodging', 'amount': float(gst.amount), 'note': 'gst'})
            else:
                item = ExpenseItem(
                    claim=claim,
                    category=category,
                    amount=Decimal(str(it.get('amount', 0))),
                    description=it.get('description', ''),
                    proof_reference=it.get('proof_reference', ''),
                    check_in_date=it.get('check_in_date') or None,
                    check_out_date=it.get('check_out_date') or None,
                    nights=it.get('nights') or None,
                    city=it.get('city') or None,
                )
                item.save()
                created.append({'id': item.id, 'category': item.category, 'amount': float(item.amount)})
        except Exception as e:
            created.append({'error': str(e), 'item': it})

    return Response({'created': created, 'count': len(created)})


# ─────────────────────────────────────────────
# Admin endpoints
# ─────────────────────────────────────────────

class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            return request.user.profile.role == 'admin'
        except:
            return False


@api_view(['GET'])
@permission_classes([IsAdmin])
def admin_overview(request):
    """System-wide overview for the admin: totals, alerts, activity."""
    from django.db.models import Sum, Count, Q

    users_count = UserProfile.objects.count()
    users_by_role = {r: UserProfile.objects.filter(role=r).count() for r in ['employee', 'manager', 'finance', 'admin']}
    tr_count = TravelRequest.objects.count()
    tr_by_status = {s: TravelRequest.objects.filter(status=s).count() for s in ['pending', 'approved', 'rejected']}
    claim_count = ExpenseClaim.objects.count()
    claim_by_status = {s: ExpenseClaim.objects.filter(status=s).count() for s in ['draft', 'submitted', 'approved', 'paid', 'rejected']}

    total_paid = sum(float(c.payable_recoverable['payable']) for c in ExpenseClaim.objects.filter(status='paid'))
    total_pending_settlement = sum(float(c.payable_recoverable['payable']) for c in ExpenseClaim.objects.filter(status__in=['approved']))

    # Outstanding advances (disbursed but claim not paid)
    outstanding_advances = []
    for tr in TravelRequest.objects.filter(advance_disbursed_at__isnull=False):
        claim = tr.expense_claims.first()
        if not claim or claim.status != 'paid':
            days = (timezone.now().date() - tr.advance_disbursed_at.date()).days
            outstanding_advances.append({
                'tr_id': tr.id,
                'employee': tr.employee.get_full_name(),
                'destination': tr.destination,
                'amount': float(tr.advance_disbursed_amount or 0),
                'days_outstanding': days,
                'claim_status': claim.status if claim else 'no_claim',
            })
    outstanding_total = sum(o['amount'] for o in outstanding_advances)

    # Advances on hold with reasons
    holds = []
    for tr in TravelRequest.objects.filter(advance_review_note__gt='', advance_disbursed_at__isnull=True):
        holds.append({
            'tr_id': tr.id,
            'employee': tr.employee.get_full_name(),
            'destination': tr.destination,
            'note': tr.advance_review_note,
            'by': tr.advance_review_by.get_full_name() if tr.advance_review_by else None,
            'at': tr.advance_review_at.isoformat() if tr.advance_review_at else None,
            'follow_up': tr.advance_follow_up_note or None,
        })

    return Response({
        'users': {'total': users_count, 'by_role': users_by_role},
        'travel_requests': {'total': tr_count, 'by_status': tr_by_status},
        'claims': {'total': claim_count, 'by_status': claim_by_status},
        'money': {
            'total_paid': total_paid,
            'pending_settlement': total_pending_settlement,
            'outstanding_advances_total': outstanding_total,
            'outstanding_advances_count': len(outstanding_advances),
        },
        'outstanding_advances': outstanding_advances,
        'holds': holds,
    })


@api_view(['GET'])
@permission_classes([IsAdmin])
def admin_policy(request):
    """Returns the current policy rules (from expense_policy.md, hardcoded for demo)."""
    return Response({
        'document': 'NTX-HR-POL-11',
        'revision': 'Rev 4',
        'effective_date': '2026-04-01',
        'applies_to': 'All India-based employees',
        'lodging_limits': {
            'tier1_cities': ['Bengaluru', 'Mumbai', 'Delhi NCR', 'Hyderabad', 'Chennai', 'Pune', 'Kolkata'],
            'tier1_per_night': 6000,
            'tier2_per_night': 4000,
            'tier3_per_night': 2800,
            'note': 'Room tariff excluding taxes. Taxes are reimbursable in full. Tariff excess is disallowed.'
        },
        'meal_limits': {
            'tier1_per_day': 1500,
            'other_per_day': 1000,
            'receipt_threshold': 500,
            'note': 'Travel days count as full days. Meal claims are on actuals up to the limit and need bills above ₹500.'
        },
        'business_entertainment': {
            'prior_approval_threshold': 2000,
            'approver': 'Head of Department',
            'requirements': 'Attendee names and organisation must be included.'
        },
        'advance_policy': {
            'max_percent': 60,
            'basis': 'estimated employee-borne cost',
            'recovery': 'If claim < advance, balance recovered from next payroll',
        },
        'non_reimbursable': [
            'Laundry, mini bar, in-room entertainment, spa, gym',
            'Personal phone or data charges',
            'Alcohol (except in approved business entertainment)',
            'Fines, penalties, traffic challans',
            'Travel insurance purchased independently',
            'Expenses incurred by any person other than the claimant',
        ],
        'approval_matrix': [
            {'range': 'Up to ₹25,000', 'approvers': 'Reporting Manager'},
            {'range': '₹25,001 – 75,000', 'approvers': 'Reporting Manager, Head of Department'},
            {'range': '₹75,001 – 2,00,000', 'approvers': 'Reporting Manager, HoD, Head of Division'},
            {'range': 'Above ₹2,00,000, or international', 'approvers': 'Manager, HoD, Div Head, MD/CEO'},
        ],
        'submission_window_days': 7,
        'payment_run_dates': ['10th', '25th'],
    })


@api_view(['GET'])
@permission_classes([IsAdmin])
def admin_organization(request):
    """Full organization tree with reporting hierarchy."""
    users_data = []
    for profile in UserProfile.objects.select_related('user', 'reporting_manager').order_by('role', 'user__username'):
        users_data.append({
            'username': profile.user.username,
            'name': profile.user.get_full_name(),
            'email': profile.user.email,
            'role': profile.role,
            'department': profile.department,
            'reporting_manager': profile.reporting_manager.get_full_name() if profile.reporting_manager else None,
            'reporting_manager_username': profile.reporting_manager.username if profile.reporting_manager else None,
            'subordinate_count': profile.user.subordinates.count(),
        })
    return Response({'users': users_data, 'total': len(users_data)})
