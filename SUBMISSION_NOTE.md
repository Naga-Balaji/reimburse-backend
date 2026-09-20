# Reimburse — Submission Note

## What I understood the problem to be

The problem statement asks for something that removes three specific pains: the 25 minutes of manual form-filling, the errors that come from that manual entry, and the two-week follow-ups asking Finance about the money. The pack itself is a signal — 15 emails from one trip, with attachments, duplicates, colleague forwards, promotional noise, a failed payment then a resend — this is not a "build me a nice form" problem, it is a "the form itself is a symptom" problem.

## What I built

A Django + React + Tailwind app with three layers that together address all three pains:

1. **Deterministic email parsers** (`core/parsers.py`) that handle every email format in the sample pack — Uber, MakeMyTrip flight vs. hotel-voucher vs. hotel-tax-invoice, self-forwarded dinner bills — and correctly filter noise (promos, colleague forwards, payment failures, duplicates by amount+date+route). Tested against all 15 sample emails: every one lands in the correct bucket.

2. **A hybrid LLM fallback** via OpenRouter for unknown senders (currently DeepSeek V4 Flash → openrouter/free) — opt-in on the Import screen because free-tier latency is 30–60s per call. This is the "17th email format we haven't seen" safety net, not the primary parser.

3. **An AI Verification Assistant** for approvers (manager and finance). When a claim is opened, the panel gathers the current claim, the employee's past claim history, and peer-baseline data for the same destination, sends this to the LLM with the company's expense policy, and returns a structured recommendation (approve/return/reject) with policy-compliance checks, behaviour comparison, peer position, and specific attention items citing policy sections. If the LLM is rate-limited or unavailable, a rule-based fallback produces the same shape — the reviewer is never blocked.

Around all of that: standard workflow (travel request → approval → advance → claim → multi-level approval by amount → finance verification → payout), role-scoped dashboards (employee/manager/finance each get a purpose-built one, with pending items highlighted), and a live workflow stepper on every claim so the employee never has to ask "where is it."

## Assumptions I made

- Employees upload `.eml` files or paste raw email text. The next step would be an IMAP poll or a shared mailbox forwarder; that's plumbing, not product.
- Proof references are text (e.g., `hotel_invoice_1188.png`), not actual file attachments. Adding S3 uploads was scope-cut.
- Payment release is UI-only — Finance clicks "Verify & Pay" and the claim moves to `paid`; no bank rail.
- The manager chain in the seed data (Chaitanya → Suresh → Meera → Arvind → Nandita) is used to determine approval levels dynamically based on claim value per policy §2, but only the manager and finance approvals actually run in the demo (small claim <₹25k). Higher tiers would trigger HoD/Div Head/MD automatically.
- Free-tier LLMs on OpenRouter rate-limit aggressively. The rule-based fallback exists specifically for this — the demo will show either the AI response or the rule-based analysis, and it always shows the same shape.

## Design decisions worth calling out

### Two approval stages, not one — because the reviewer's job changes over time

A subtle but critical design call: the manager approves **twice**, on **two different objects**, at **two different times**, with **different evidence available**:

1. **Pre-trip: Travel Request approval.** Manager reviews the plan — destination, dates, purpose, estimated cost, advance amount. **No receipts exist yet.** The manager is deciding: is this trip justified? Is ₹40,000 a reasonable estimate? Should we release ₹15,000 as advance?

2. **Post-trip: Expense Claim approval.** Manager reviews actual receipts against the plan they approved earlier. **Now proof documents exist.** The manager is deciding: did the actual spending stay within policy? Are there policy violations? Is the ₹42,150 actual close enough to the ₹40,000 estimated?

These are genuinely different tasks. Bundling them into one approval would force the manager to either approve blindly (before receipts exist) or block the employee (can't book flights until every receipt is in).

**How this shows up in the app:**
- `TravelRequest.status` (pending/approved/rejected) — the pre-trip decision
- `ExpenseClaim.status` (draft/submitted/approved/paid) — the post-trip decision
- The **Employee Context panel** at claim-review time shows the manager a plan-vs-actual comparison: estimated ₹48,000 → actual ₹27,113 (-43.5% vs estimate) — with a warning if the actual claim is >15% over the approved estimate. This anchors the manager on what they originally approved and highlights any deviation that needs attention.
- The **AI Verification Assistant** also has access to the original estimate as context, so its recommendation factors in budget adherence, not just per-item policy compliance.

### Advance is requested upfront with the Travel Request, not after approval

Nortex's actual process bundles them — sample email 01 asks for approval and advance in a single message ("Estimated spend: INR 48,000 / Advance requested: INR 20,000"), and the Excel form (`Travel_Expense_Forms_Template.xlsx`) has "Travel advance requested" as a field on the same form as the travel request. Policy §1.2 explicitly permits this. Our app matches that: employees enter both when creating a Travel Request, manager approves the package, Finance disburses.

The alternative — separate advance request after travel approval — has its merits (managers can approve the trip but adjust the cash number, cancelled trips don't need advance reversal), but it would re-engineer Nortex's process rather than automate it. Different companies would want it differently (startups with corporate cards need no advance at all; frequent travelers might have standing imprest), so in a productised version this would become an admin-configurable workflow. For Nortex specifically, upfront is correct.

**Known simplification:** we treat "TR approved" as "advance drawn" in the claim's summary math. In reality those are two events (approval → Finance disburses → advance actually in the bank). A production version would add `advance_status: requested|approved|disbursed|adjusted` on the TravelRequest so the claim summary knows whether the advance is real cash or still in flight.

### AI is an advisor, never a decider

The AI Verification Assistant surfaces a recommendation with confidence, policy checks, employee-behaviour comparison, and attention items — but the approve/reject button is always the human's. This is a deliberate product call. If AI could auto-approve, the manager's accountability shifts to the algorithm; and free-tier models fail often enough that we'd routinely be blocked. Advisor pattern keeps the human in the loop, uses AI where it's strongest (reading policy + summarising context), and degrades gracefully to the rule-based fallback when the LLM is down.

### Financial actions require context, not just buttons

Finance is the only role in the app that moves actual money. Disbursing an advance and paying a settlement are both one-way, hard-to-reverse actions. So neither should ever happen with a single-click on a table row — the person clicking needs to see the full picture first.

Advance disbursement has a dedicated review page at `/advance/:id/review` that shows: the trip context, the employee's outstanding advances (with age chips — 30+ days highlights red), historical disbursement variance (avg over/underspend across past trips, colour-coded), the 60% policy cap with any excess flagged, and an editable amount field so Finance can release less than requested if the outstanding balance is high. The dashboard's "Disburse advance" button navigates here rather than firing the action directly.

This is the "notification-vs-full-picture" trade-off. Notifications are for events already decided; money movement is a decision — it deserves the full picture.

### Two workflow lanes: business approvals + finance disbursements

Real expense reimbursement has TWO parallel tracks running through a claim's lifecycle: business people deciding *whether* to pay (manager → HoD → division → MD), and finance people tracking *what has actually been paid* (advance disbursement → final settlement). Collapsing them into one linear stepper loses information — the employee can't see whether their advance has actually left Finance's till; Finance can't see outstanding advance liability separate from settlements waiting for approval.

Our stepper renders both as visually distinct lanes: green circles for business-approval steps, emerald circles with a ₹ badge for finance-operations steps. Each step carries a sub-label showing who acted (Suresh Iyer, Ravi Menon) or what was moved (Adv ₹20,000, ref ADV/2026/0619). Finance has its own dashboard section — "Advances Awaiting Disbursement" — that surfaces approved TRs where the money hasn't yet been released, distinct from the settlements queue.

A production version would separate this out entirely into a `Payment` model (with type = advance / settlement / recovery, its own reference, timestamp, released_by, method). For this build we added the four disbursement fields directly on the TravelRequest, which is enough to close the audit-trail gap without introducing a new model.

### Every claim item carries its actual proof document, and approvers can view it inline

Text references to receipts (`hotel_invoice_1188.png`) are useless — the approver has to trust the number. That defeats the purpose. Every ExpenseItem now has an optional `proof_file` field (FileField, uploads to `/media/proofs/`). The `ProofViewer` component in the claim view renders images natively, PDFs in an iframe, and offers download/open-new-tab for anything else. This closes the audit loop: the approver sees a claimed amount, clicks the proof pill, sees the actual invoice, verifies each line item with their own eyes (including confirming that the disallowed items — laundry, mini-bar, in-room dining — really are on the folio), and approves with confidence rather than blind trust.

### Deterministic parsers first, LLM as fallback

Not the other way around. The pack has 15 emails from known senders (Uber, MakeMyTrip, one hotel). Pattern parsers hit 100%, run in <100ms, and cost nothing. An LLM would take 30–60s per email on free tier and cost tokens. The LLM is there for the 16th format we haven't seen yet — surfaced as an opt-in toggle on the Import screen so demos aren't slow.

## What I deliberately left out

- **OCR for image-only receipts** — the dinner bill amount is entered manually since the parser can only see the email metadata, not what's in the attached PNG (though the image itself IS attached and viewable by the approver — see ProofViewer)
- **Per-day meal cap enforcement** — implemented lodging limits and business-entertainment threshold; meal cap would be similar logic
- **Admin UI for editing policy / configuring workflows** — the demo video showed a full workflow builder; that is a substantial product on its own and beyond the scope of an 8-hour build
- **Actual disbursement integration** — no NEFT/UPI hook
- **Audit trail beyond approvals** — approval records are stamped with approver, decision, remarks, timestamp; a full activity log per claim would be additional

## Known debt (honest)

- **Frontend has ~10 unused-import ESLint warnings** across a few components (Login, PolicyView, TravelRequestDetail, TravelRequests). Vercel is deployed with `CI=false` to skip strict warnings-as-errors. Cleanup is trivial (delete unused imports) — I chose to ship the demo first. Would fix with `npx eslint --fix src/` + add husky + lint-staged for pre-commit hooks in a real product.
- No test suite (`pytest` for the DRF viewsets + `jest` for React components). Would be my day-1 addition once the API surface stabilises.
- Hardcoded strings that should be constants: Tier-1 city list, LLM prompt templates, timeout thresholds. Fine for a first cut; extract to a config module before onboarding a second engineer.

## Where it breaks

- **Free-tier LLM rate limits** — the primary and fallback models can both hit 429. The rule-based fallback then runs and produces sensible analysis. Adding an Anthropic key would remove this entirely (my `core/llm.py` supports any OpenRouter model via `OPENROUTER_MODEL`).
- **Uber parser assumes "Thanks for riding, <name>" line** — if Uber changes their email template, the extractor breaks. That's why the LLM fallback is there.
- **Colleague forward detection is by first name** — two employees named "Deepa" would false-negative. In production I'd match by email address at the header level.
- **Hotel invoice line-item split relies on double-space alignment** — works for the sample pack; a hotel using tabs or a table structure would need a different parser. Again, LLM fallback covers this.
- **No test suite** — 8 hours meant choosing between polish and tests; I chose polish. The parser is deterministic though, and I ran it against all 15 sample emails to verify.

## What I'd do next (if this were a real product, not a submission)

1. **Email server integration** — poll IMAP or run as a Gmail add-on. Uploading `.eml` files is fine for the demo but real employees won't do that.
2. **Receipt OCR** — for image-only bills like the dinner receipt, use vision LLM to extract amount + attendees.
3. **Learn from approvals** — every "return" with remarks is training data. Feed it back to make the AI Verification Assistant sharper over time.
4. **Slack/Teams surface** — approvers should be able to approve from a notification without opening the app.
5. **Full policy editor** — the video reference showed a workflow builder; that's the natural admin surface once the base product is stable.

## Time spent

Roughly 10 hours across understanding the pack, building the workflow, building the email parsers, building the AI insights layer, and testing. I used AI tooling (Claude Code) throughout, per the assignment brief — the architectural decisions, product trade-offs (hybrid parser vs. pure LLM, opt-in vs. always-on AI fallback, rule-based safety net for insights), and what to cut are mine to explain and defend.
