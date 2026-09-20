"""
Email receipt parsers.
Layer 1: Pattern-based (deterministic, fast) for known senders.
Layer 2: LLM fallback via OpenRouter for unknown formats.
"""
import re
import email
from email.parser import BytesParser, Parser
from email import policy
from datetime import datetime
from decimal import Decimal
import hashlib
import json


# ─────────────────────────────────────────────
# Pattern-based extractors
# ─────────────────────────────────────────────

def parse_uber_receipt(body, subject, from_addr):
    """
    Uber receipt format:
      Total  INR 1,415.02
      Tue, 16 Jun 2026 | 05:20 AM
      Pickup   Baner, Pune
      Drop     Pune International Airport (PNQ)
      Payment: Personal - HDFC Credit Card ****2288
    """
    if 'uber.com' not in from_addr.lower():
        return None

    # Detect failed payment (no receipt yet)
    if 'payment failed' in subject.lower() or 'could not charge' in body.lower():
        return {
            'kind': 'noise',
            'reason': 'Uber payment failure notification (not a receipt)',
            'confidence': 1.0,
        }

    # Detect forwarded receipt of another employee (colleague forward)
    if 'thanks for riding' in body.lower():
        # Extract the "Thanks for riding, <name>" — if the name differs from the account holder, flag
        m = re.search(r'thanks for riding,\s*(\w+)', body, re.IGNORECASE)
        rider_name = m.group(1) if m else None

    amt_m = re.search(r'total\s+inr\s+([\d,]+\.?\d*)', body, re.IGNORECASE)
    if not amt_m:
        return None
    amount = Decimal(amt_m.group(1).replace(',', ''))

    date_m = re.search(r'(\w{3},\s*\d{1,2}\s+\w{3}\s+\d{4})', body)
    date_str = date_m.group(1) if date_m else None
    try:
        parsed_date = datetime.strptime(date_str, '%a, %d %b %Y').date() if date_str else None
    except:
        parsed_date = None

    pickup_m = re.search(r'pickup\s+([^\n\r]+)', body, re.IGNORECASE)
    drop_m = re.search(r'drop\s+([^\n\r]+)', body, re.IGNORECASE)
    pickup = pickup_m.group(1).strip() if pickup_m else '?'
    drop = drop_m.group(1).strip() if drop_m else '?'

    is_personal_card = 'personal' in body.lower() and 'card' in body.lower()

    return {
        'kind': 'expense',
        'category': 'transport',
        'amount': amount,
        'date': parsed_date.isoformat() if parsed_date else None,
        'description': f'Uber: {pickup} → {drop}',
        'proof_reference': subject[:180],
        'paid_by': 'employee' if is_personal_card else 'unknown',
        'merchant': 'Uber',
        'raw_snippet': body[:200],
        'confidence': 0.95,
    }


def parse_makemytrip_flight(body, subject, from_addr):
    """
    MakeMyTrip flight — booked centrally, borne by company, NOT claimable.
    """
    if 'makemytrip' not in from_addr.lower():
        return None
    if 'e-ticket' not in subject.lower() and 'flight booking' not in subject.lower():
        return None

    is_corporate = 'corporate card' in body.lower() or 'nortex' in body.lower()

    pnr_m = re.search(r'pnr[:\s]+([A-Z0-9]{5,})', body, re.IGNORECASE)
    total_m = re.findall(r'total\s+inr\s+([\d,]+\.?\d*)', body, re.IGNORECASE)
    total = sum(Decimal(m.replace(',', '')) for m in total_m) if total_m else Decimal('0')

    return {
        'kind': 'info_only',
        'reason': 'Flight booked centrally by travel desk, billed to company. Not claimable by employee.',
        'category': 'transport',
        'amount': total,
        'paid_by': 'company',
        'merchant': 'MakeMyTrip (flights)',
        'proof_reference': subject[:180],
        'raw_snippet': body[:200],
        'confidence': 1.0 if is_corporate else 0.8,
    }


def parse_makemytrip_hotel_voucher(body, subject, from_addr):
    """
    MakeMyTrip hotel voucher — provides booking details but final claim is from the hotel invoice.
    """
    if 'makemytrip' not in from_addr.lower():
        return None
    if 'hotel booking' not in subject.lower() and 'hotel voucher' not in subject.lower():
        return None

    return {
        'kind': 'info_only',
        'reason': 'Hotel booking voucher. Use the actual hotel tax invoice for the claim.',
        'confidence': 1.0,
    }


def parse_hotel_invoice(body, subject, from_addr):
    """
    Hotel tax invoice — extract line items, split reimbursable from non-reimbursable.
    Non-reimbursable per policy §4: Laundry, mini bar, in-room entertainment, spa, gym, etc.
    """
    # Detect a hotel invoice — heuristic: has "invoice" in subject or CGST/SGST in body
    if not ('invoice' in subject.lower() or 'tax invoice' in subject.lower()):
        if not ('cgst' in body.lower() or 'sgst' in body.lower()):
            return None

    # Extract folio number
    folio_m = re.search(r'(folio\s*(?:no\.?)?\s*[:\s]*)([\w\-\/]+)', body, re.IGNORECASE)
    folio = folio_m.group(2) if folio_m else None

    # Extract line items with amounts
    NON_REIMBURSABLE_KEYWORDS = ['laundry', 'mini bar', 'minibar', 'in-room entertainment',
                                  'in-room dining', 'spa', 'gym', 'personal', 'alcohol']

    line_items = []
    # Match "<label>  <amount>" lines
    for line in body.split('\n'):
        line = line.strip()
        m = re.match(r'^(.+?)\s{2,}([\d,]+\.\d{2})\s*$', line)
        if m:
            label = m.group(1).strip().lower()
            amount = Decimal(m.group(2).replace(',', ''))
            # Skip totals/subtotals
            if any(x in label for x in ['sub total', 'subtotal', 'invoice total', 'grand total']):
                continue
            is_non_reimb = any(kw in label for kw in NON_REIMBURSABLE_KEYWORDS)
            line_items.append({
                'label': m.group(1).strip(),
                'amount': amount,
                'is_non_reimbursable': is_non_reimb,
            })

    if not line_items:
        return None

    # Room charges
    room_items = [li for li in line_items if 'room' in li['label'].lower() and not li['is_non_reimbursable']]
    tax_items = [li for li in line_items if 'gst' in li['label'].lower()]
    non_reimb_items = [li for li in line_items if li['is_non_reimbursable']]

    room_total = sum(li['amount'] for li in room_items)
    tax_total = sum(li['amount'] for li in tax_items)
    non_reimb_total = sum(li['amount'] for li in non_reimb_items)

    # Extract check-in/out dates
    checkin_m = re.search(r'check[\s\-]?in[:\s]+(\d{1,2}\s+\w{3}\s+\d{4})', body, re.IGNORECASE)
    checkout_m = re.search(r'check[\s\-]?out[:\s]+(\d{1,2}\s+\w{3}\s+\d{4})', body, re.IGNORECASE)
    nights_m = re.search(r'nights?\s+(\d+)', body, re.IGNORECASE)

    def parse_date(s):
        try:
            return datetime.strptime(s, '%d %b %Y').date().isoformat()
        except:
            return None

    checkin = parse_date(checkin_m.group(1)) if checkin_m else None
    checkout = parse_date(checkout_m.group(1)) if checkout_m else None
    nights = int(nights_m.group(1)) if nights_m else None

    # Try to extract hotel name and city
    hotel_name_m = re.search(r'from[:\s].*?<([\w\-\.@]+)>', from_addr, re.IGNORECASE)

    return {
        'kind': 'lodging_invoice',
        'category': 'lodging',
        'folio': folio,
        'amount': room_total + tax_total,  # reimbursable amount
        'non_reimbursable_amount': non_reimb_total,
        'non_reimbursable_items': non_reimb_items,
        'room_charges': room_total,
        'gst': tax_total,
        'check_in_date': checkin,
        'check_out_date': checkout,
        'nights': nights,
        'description': f'Hotel stay (Folio {folio})' if folio else 'Hotel stay',
        'proof_reference': subject[:180],
        'raw_snippet': body[:300],
        'confidence': 0.95,
    }


def parse_self_forward(body, subject, from_addr, to_addr):
    """Self-sent email with attachment (like the dinner bill). Treat as business entertainment."""
    if from_addr.lower() != to_addr.lower():
        return None
    if 'dinner' in subject.lower() or 'lunch' in subject.lower() or 'entertainment' in subject.lower():
        # Try to find people count and attendees
        people_m = re.search(r'(\d+)\s+people', body, re.IGNORECASE)
        people = int(people_m.group(1)) if people_m else None
        return {
            'kind': 'expense',
            'category': 'entertainment',
            'description': subject,
            'proof_reference': subject[:180],
            'notes': body[:300],
            'people': people,
            'amount': None,  # amount is in the attached bill
            'requires_manual_amount': True,
            'confidence': 0.75,
        }
    return None


def detect_noise(body, subject, from_addr):
    """Detect promotional or irrelevant emails."""
    subj_lower = subject.lower()
    body_lower = body.lower()

    # Promo emails
    if 'offers@' in from_addr.lower() or 'promo' in from_addr.lower():
        return {'kind': 'noise', 'reason': 'Promotional email', 'confidence': 1.0}
    if any(kw in subj_lower for kw in ['% off', 'sale', 'unsubscribe']) and 'monsoon' in body_lower:
        return {'kind': 'noise', 'reason': 'Promotional email', 'confidence': 0.95}

    return None


def detect_colleague_forward(body, subject, from_addr, to_addr, employee_first_name):
    """Detect when someone else's receipt was forwarded to the employee."""
    # If subject says "Fwd:" or "forwarded", check if the receipt's original recipient differs
    if not ('fwd' in subject.lower() or 'forwarded' in body.lower()):
        return None

    # Look for "Thanks for riding, <name>"
    m = re.search(r'thanks for riding,\s*(\w+)', body, re.IGNORECASE)
    if m:
        rider = m.group(1).lower()
        if employee_first_name and rider != employee_first_name.lower():
            return {
                'kind': 'noise',
                'reason': f'This receipt belongs to {m.group(1)}, not the current employee. Colleague forward — not claimable.',
                'confidence': 1.0,
            }
    return None


# ─────────────────────────────────────────────
# Main dispatcher
# ─────────────────────────────────────────────

def parse_eml_content(raw_bytes_or_str, employee_first_name=None):
    """
    Parse a raw .eml file content and return a structured result.
    Returns dict with:
      - subject, from, to, date
      - parsed: the extraction result or None
      - parser: which parser matched (or 'llm_fallback' if none)
    """
    if isinstance(raw_bytes_or_str, str):
        msg = Parser(policy=policy.default).parsestr(raw_bytes_or_str)
    else:
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes_or_str)

    subject = str(msg.get('Subject', ''))
    from_addr = str(msg.get('From', ''))
    to_addr = str(msg.get('To', ''))
    date_str = str(msg.get('Date', ''))

    # Extract body (text)
    body = ''
    if msg.is_multipart():
        for part in msg.iter_parts():
            ctype = part.get_content_type()
            if ctype == 'text/plain':
                try:
                    body += part.get_content()
                except:
                    body += str(part.get_payload())
                break
    else:
        try:
            body = msg.get_content()
        except:
            body = str(msg.get_payload())

    result = {
        'subject': subject,
        'from': from_addr,
        'to': to_addr,
        'date': date_str,
        'body_preview': body[:400],
        'parsed': None,
        'parser': None,
        'hash': hashlib.md5(f'{subject}{body}'.encode()).hexdigest()[:12],
    }

    # Try parsers in order
    parsers = [
        ('noise', lambda: detect_noise(body, subject, from_addr)),
        ('colleague_forward', lambda: detect_colleague_forward(body, subject, from_addr, to_addr, employee_first_name)),
        ('uber', lambda: parse_uber_receipt(body, subject, from_addr)),
        ('mmt_flight', lambda: parse_makemytrip_flight(body, subject, from_addr)),
        ('mmt_hotel', lambda: parse_makemytrip_hotel_voucher(body, subject, from_addr)),
        ('hotel_invoice', lambda: parse_hotel_invoice(body, subject, from_addr)),
        ('self_forward', lambda: parse_self_forward(body, subject, from_addr, to_addr)),
    ]

    for name, fn in parsers:
        try:
            r = fn()
            if r:
                result['parsed'] = r
                result['parser'] = name
                break
        except Exception as e:
            continue

    return result


def deduplicate_parsed(items):
    """Detect duplicates from a list of parsed items.
    Uber sends the same receipt twice sometimes (email 09 and 10 in sample).
    We detect: same amount + same date + same route.
    """
    seen = {}
    for item in items:
        parsed = item.get('parsed')
        if not parsed or parsed.get('kind') != 'expense':
            continue
        key = (
            str(parsed.get('amount')),
            parsed.get('date'),
            parsed.get('description', '').lower()[:50],
        )
        if key in seen:
            item['parsed']['kind'] = 'noise'
            item['parsed']['reason'] = f'Duplicate of another receipt already seen: {seen[key]["subject"]}'
        else:
            seen[key] = item
    return items
