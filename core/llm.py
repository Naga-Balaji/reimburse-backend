"""
LLM integration via OpenRouter.
Two uses:
1. Fallback email parsing for unknown senders (from parsers.py)
2. AI Insights for approvers (manager/finance) reviewing claims
"""
import os
import json
import requests
from decimal import Decimal
from django.db.models import Avg, Sum, Count
from datetime import timedelta


OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
DEFAULT_MODEL = os.environ.get('OPENROUTER_MODEL', 'deepseek/deepseek-v4-flash-0731:free')
FALLBACK_MODEL = os.environ.get('OPENROUTER_FALLBACK_MODEL', 'google/gemma-4-31b-it:free')


def call_openrouter(system, user, model=None, expect_json=True):
    """
    Call OpenRouter with a system + user message.
    Tries DEFAULT_MODEL first, falls back to FALLBACK_MODEL if it fails.
    Returns parsed JSON if expect_json, else raw text.
    """
    if not OPENROUTER_API_KEY:
        return {'error': 'no_api_key', 'message': 'OpenRouter API key not configured. Add OPENROUTER_API_KEY to .env'}

    models_to_try = [model] if model else [DEFAULT_MODEL, FALLBACK_MODEL]
    last_error = None

    for m in models_to_try:
        if not m:
            continue
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers={
                    'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': 'http://localhost:3000',
                    'X-Title': 'Reimburse - Expense App',
                },
                json={
                    'model': m,
                    'messages': [
                        {'role': 'system', 'content': system},
                        {'role': 'user', 'content': user},
                    ],
                    'temperature': 0.1,
                    'max_tokens': 2000,
                },
                timeout=90,
            )
            response.raise_for_status()
            data = response.json()
            content = data['choices'][0]['message']['content']

            if expect_json:
                import re
                # Try triple-backtick JSON block first
                fenced = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content)
                if fenced:
                    parsed = json.loads(fenced.group(1))
                    parsed['_model_used'] = m
                    return parsed
                # Fall back to plain JSON extraction
                match = re.search(r'\{[\s\S]*\}', content)
                if match:
                    parsed = json.loads(match.group(0))
                    parsed['_model_used'] = m
                    return parsed
                last_error = {'error': 'no_json_found', 'raw': content[:500]}
                continue
            return content
        except requests.exceptions.Timeout:
            last_error = {'error': 'timeout', 'message': f'Timed out on {m}'}
            continue
        except Exception as e:
            last_error = {'error': 'llm_error', 'message': f'{m}: {str(e)}'}
            continue

    return last_error or {'error': 'all_models_failed'}


# ─────────────────────────────────────────────
# 1. LLM fallback for email parsing
# ─────────────────────────────────────────────

EMAIL_EXTRACTION_SYSTEM = """You extract expense information from emails.

Return a JSON object with these fields:
{
  "kind": "expense" | "noise" | "info_only" | "unclear",
  "category": "lodging" | "transport" | "meals" | "entertainment" | null,
  "amount": <decimal or null>,
  "currency": "INR",
  "date": "YYYY-MM-DD" or null,
  "description": "<short human-readable description>",
  "merchant": "<vendor name>",
  "paid_by": "employee" | "company" | "unknown",
  "confidence": <0-1 float>,
  "reason": "<if noise, explain why>"
}

Rules:
- "noise" = promotional, spam, notification not receipt
- "info_only" = confirmation but not the actual expense record (e.g., hotel booking voucher; the real bill comes from the hotel)
- "expense" = an actual reimbursable receipt
- If paid on a corporate card, mark paid_by = "company"
- Be conservative — if unsure, mark "unclear" with reason
"""


def llm_parse_email(subject, from_addr, body):
    """LLM-based fallback for unknown email formats."""
    user_msg = f"""Subject: {subject}
From: {from_addr}

Body:
{body[:3000]}

Extract expense info as JSON."""
    return call_openrouter(EMAIL_EXTRACTION_SYSTEM, user_msg)


# ─────────────────────────────────────────────
# 2. AI Insights for approvers
# ─────────────────────────────────────────────

def gather_claim_context(claim):
    """Assemble context about the claim, employee history, and peers."""
    from .models import ExpenseClaim, ExpenseItem, TravelRequest

    employee = claim.employee
    destination = claim.travel_request.destination

    # Current claim
    items = list(claim.items.values(
        'category', 'amount', 'description', 'proof_reference',
        'city', 'nights', 'is_disallowed', 'disallowed_amount', 'claimed_amount', 'disallow_reason'
    ))

    # Employee's past claims (excluding current)
    past_claims = ExpenseClaim.objects.filter(
        employee=employee,
        status__in=['approved', 'paid']
    ).exclude(id=claim.id).order_by('-created_at')[:10]

    past_summary = []
    for pc in past_claims:
        past_summary.append({
            'destination': pc.travel_request.destination,
            'nights': pc.travel_request.to_date - pc.travel_request.from_date,
            'total_claimed': float(pc.total_claimed),
            'net_reimbursable': float(pc.net_reimbursable),
            'disallowed': float(pc.total_disallowed),
            'status': pc.status,
        })

    # Same-destination trips (across the org, for peer baseline)
    peer_claims = ExpenseClaim.objects.filter(
        travel_request__destination__iexact=destination,
        status__in=['approved', 'paid']
    ).exclude(id=claim.id).exclude(employee=employee)

    peer_stats = {
        'count': peer_claims.count(),
        'avg_total': float(peer_claims.aggregate(Avg('items__claimed_amount'))['items__claimed_amount__avg'] or 0),
    }
    # Compute avg net properly
    peer_totals = []
    for pc in peer_claims:
        peer_totals.append(float(pc.net_reimbursable))
    peer_stats['avg_net'] = sum(peer_totals) / len(peer_totals) if peer_totals else 0

    # Same-destination trips by this employee
    same_dest_own = [p for p in past_summary if p['destination'].lower() == destination.lower()]

    return {
        'claim_id': claim.id,
        'employee': {
            'name': employee.get_full_name(),
            'department': getattr(employee.profile, 'department', ''),
        },
        'trip': {
            'destination': destination,
            'from_date': claim.travel_request.from_date.isoformat(),
            'to_date': claim.travel_request.to_date.isoformat(),
            'purpose': claim.travel_request.purpose,
            'estimated_cost': float(claim.travel_request.estimated_cost),
            'advance_requested': float(claim.travel_request.advance_requested),
        },
        'current_claim': {
            'total_claimed': float(claim.total_claimed),
            'total_disallowed': float(claim.total_disallowed),
            'net_reimbursable': float(claim.net_reimbursable),
            'payable': float(claim.payable_recoverable['payable']),
            'items': items,
        },
        'employee_history': {
            'total_past_claims': len(past_summary),
            'past_claims': past_summary[:5],
            'avg_total_past': (sum(p['total_claimed'] for p in past_summary) / len(past_summary)) if past_summary else 0,
            'same_destination_trips': same_dest_own,
        },
        'peer_baseline': peer_stats,
    }


POLICY_SUMMARY = """
Nortex Industries Travel & Expense Policy (NTX-HR-POL-11 Rev 4):

Lodging limits (per night, ex-taxes):
- Tier-1 (Bengaluru, Mumbai, Delhi NCR, Hyderabad, Chennai, Pune, Kolkata): ₹6,000
- Tier-2: ₹4,000
- Tier-3 and others: ₹2,800
- Room taxes reimbursable in full; excess of tariff is disallowed.

Meals (per day, on actuals up to limit, receipts >₹500):
- Tier-1: ₹1,500
- Tier-2 and below: ₹1,000

Local conveyance: on actuals with receipts. Airport transfers covered.

Business entertainment: Requires attendee names and organisation.
Prior HoD approval REQUIRED if >₹2,000.

Non-reimbursable (must be excluded even if on hotel folio):
- Laundry, mini bar, in-room entertainment, spa, gym
- Personal phone/data
- Alcohol (except in approved business entertainment)
- Fines, penalties, traffic challans
- Travel insurance
- Expenses of any person other than the claimant

Approval matrix (based on claim value):
- Up to ₹25,000: Reporting Manager
- ₹25,001-75,000: Manager + HoD
- ₹75,001-2,00,000: Manager + HoD + Head of Division
- >₹2,00,000 or international: All above + MD/CEO
- Finance verification required on every claim.

Submission: Within 7 calendar days of return.
Every claim line requires supporting document (proof reference).
"""


INSIGHTS_SYSTEM = """You are an expense-verification assistant helping a manager or finance reviewer.
You analyze a claim and produce a JSON insights object.

Given the claim, the employee's past history, peer baseline, and company policy — produce:

{
  "recommendation": "approve" | "return" | "reject" | "investigate",
  "confidence": <0-1 float>,
  "confidence_label": "high" | "medium" | "low",
  "one_line_summary": "<one sentence explaining the recommendation>",
  "policy_compliance": [
    {"status": "pass" | "warn" | "fail", "note": "<short specific finding>"}
  ],
  "employee_behavior": {
    "past_claim_count": <int>,
    "comparison": "<how this compares to their past pattern>",
    "flags": ["<any flags>"]
  },
  "peer_comparison": {
    "note": "<how this compares to peers on similar trips>",
    "position": "below_average" | "average" | "above_average" | "no_data"
  },
  "attention_items": [
    {"severity": "info" | "warn" | "alert", "note": "<specific item requiring attention>"}
  ]
}

Be specific and cite numbers. Reference policy sections when relevant.
Focus on what the reviewer needs to decide. Don't restate what they can see.
"""


def generate_ai_insights(claim):
    """Generate AI-powered verification insights for a claim."""
    context = gather_claim_context(claim)
    user_msg = f"""Claim Context:
{json.dumps(context, indent=2, default=str)}

Company Policy Summary:
{POLICY_SUMMARY}

Generate structured verification insights."""

    result = call_openrouter(INSIGHTS_SYSTEM, user_msg)

    # If LLM fails, return a fallback deterministic insights
    if result and 'error' in result:
        return fallback_insights(claim, context, result.get('message', 'LLM unavailable'))

    return result


def fallback_insights(claim, context, error_reason):
    """Rule-based fallback when LLM is not available."""
    items = context['current_claim']['items']
    disallowed = context['current_claim']['total_disallowed']
    net = context['current_claim']['net_reimbursable']
    past_avg = context['employee_history'].get('avg_total_past', 0)
    peer_avg = context['peer_baseline'].get('avg_net', 0)

    checks = []
    attention = []

    # Rule 1: Any items disallowed?
    if disallowed > 0:
        checks.append({'status': 'warn', 'note': f'₹{disallowed:.2f} disallowed by policy'})
    else:
        checks.append({'status': 'pass', 'note': 'All items within policy limits'})

    # Rule 2: Proof references present?
    missing_proof = sum(1 for i in items if not i.get('proof_reference'))
    if missing_proof:
        checks.append({'status': 'fail', 'note': f'{missing_proof} items missing proof reference'})
    else:
        checks.append({'status': 'pass', 'note': f'All {len(items)} items have proof references'})

    # Rule 3: Business entertainment >2000?
    for i in items:
        if i['category'] == 'entertainment' and float(i['amount']) > 2000:
            attention.append({
                'severity': 'warn',
                'note': f"Business entertainment ₹{i['amount']} exceeds ₹2,000 — requires prior HoD approval per §3.5"
            })

    # Rule 4: Comparison to past
    if past_avg > 0:
        diff_pct = ((net - past_avg) / past_avg) * 100
        behavior_note = f"Employee's average past claim: ₹{past_avg:.0f}. This claim: ₹{net:.0f} ({diff_pct:+.1f}%)"
    else:
        behavior_note = "No past claim history for this employee"

    # Rule 5: Peer comparison
    if peer_avg > 0:
        peer_diff = ((net - peer_avg) / peer_avg) * 100
        if peer_diff < -10:
            position = 'below_average'
        elif peer_diff > 10:
            position = 'above_average'
        else:
            position = 'average'
        peer_note = f"Team average for similar trips: ₹{peer_avg:.0f}. This claim: ₹{net:.0f} ({peer_diff:+.1f}%)"
    else:
        position = 'no_data'
        peer_note = "No peer data for this destination"

    # Recommendation
    has_fails = any(c['status'] == 'fail' for c in checks)
    has_alerts = any(a['severity'] == 'alert' for a in attention)
    if has_fails or has_alerts:
        rec = 'return'
        summary = 'Some items need correction before approval'
    elif disallowed > 0 and disallowed > net * 0.1:
        rec = 'investigate'
        summary = 'Significant portion disallowed — review before approving'
    else:
        rec = 'approve'
        summary = 'Claim within policy and consistent with history'

    return {
        'recommendation': rec,
        'confidence': 0.7,
        'confidence_label': 'medium',
        'one_line_summary': summary,
        'policy_compliance': checks,
        'employee_behavior': {
            'past_claim_count': context['employee_history']['total_past_claims'],
            'comparison': behavior_note,
            'flags': [],
        },
        'peer_comparison': {
            'note': peer_note,
            'position': position,
        },
        'attention_items': attention,
        '_source': f'rule_based_fallback (LLM unavailable: {error_reason})',
    }
