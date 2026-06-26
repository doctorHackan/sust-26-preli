"""
Rule-based fallback ticket analyzer.

Used when the LLM service is unavailable or fails. Provides deterministic
analysis through keyword matching and heuristic mapping.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import List, Optional, Tuple

from app.models import (
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    TicketRequest,
    TicketResponse,
    TransactionHistory,
)

logger = logging.getLogger(__name__)

# ── Keyword → CaseType Mapping ──────────────────────────────────────────────

_CASE_TYPE_KEYWORDS: list[Tuple[CaseType, list[str]]] = [
    (
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING,
        [
            "otp",
            "pin",
            "password",
            "suspicious call",
            "scam",
            "phishing",
            "fraud",
            "suspicious message",
            "suspicious link",
            "social engineering",
        ],
    ),
    (
        CaseType.WRONG_TRANSFER,
        [
            "wrong number",
            "wrong person",
            "wrong transfer",
            "sent to wrong",
            "mistakenly sent",
            "accidental transfer",
            "wrong account",
            "wrong recipient",
        ],
    ),
    (
        CaseType.DUPLICATE_PAYMENT,
        [
            "duplicate",
            "charged twice",
            "double charge",
            "paid twice",
            "double payment",
            "two times",
            "twice charged",
        ],
    ),
    (
        CaseType.PAYMENT_FAILED,
        [
            "failed",
            "not completed",
            "deducted but",
            "charged but",
            "money cut",
            "balance cut",
            "transaction failed",
            "unsuccessful",
            "not received",
            "balance deducted",
        ],
    ),
    (
        CaseType.REFUND_REQUEST,
        [
            "refund",
            "money back",
            "return my",
            "give back",
            "want my money",
            "get back",
        ],
    ),
    (
        CaseType.MERCHANT_SETTLEMENT_DELAY,
        [
            "settlement",
            "merchant payment",
            "merchant not received",
            "merchant issue",
            "settlement delay",
        ],
    ),
    (
        CaseType.AGENT_CASH_IN_ISSUE,
        [
            "agent",
            "cash in",
            "cash deposit",
            "agent point",
            "agent issue",
        ],
    ),
]

# ── Static Mappings ──────────────────────────────────────────────────────────

_CASE_TO_DEPARTMENT: dict[CaseType, Department] = {
    CaseType.WRONG_TRANSFER: Department.DISPUTE_RESOLUTION,
    CaseType.PAYMENT_FAILED: Department.PAYMENTS_OPS,
    CaseType.REFUND_REQUEST: Department.DISPUTE_RESOLUTION,
    CaseType.DUPLICATE_PAYMENT: Department.PAYMENTS_OPS,
    CaseType.MERCHANT_SETTLEMENT_DELAY: Department.MERCHANT_OPERATIONS,
    CaseType.AGENT_CASH_IN_ISSUE: Department.AGENT_OPERATIONS,
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING: Department.FRAUD_RISK,
    CaseType.OTHER: Department.CUSTOMER_SUPPORT,
}

_CASE_TO_SEVERITY: dict[CaseType, Severity] = {
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING: Severity.CRITICAL,
    CaseType.WRONG_TRANSFER: Severity.HIGH,
    CaseType.DUPLICATE_PAYMENT: Severity.HIGH,
    CaseType.PAYMENT_FAILED: Severity.MEDIUM,
    CaseType.REFUND_REQUEST: Severity.MEDIUM,
    CaseType.MERCHANT_SETTLEMENT_DELAY: Severity.MEDIUM,
    CaseType.AGENT_CASH_IN_ISSUE: Severity.MEDIUM,
    CaseType.OTHER: Severity.LOW,
}

_CASE_DESCRIPTIONS: dict[CaseType, str] = {
    CaseType.WRONG_TRANSFER: "sending money to an incorrect recipient",
    CaseType.PAYMENT_FAILED: "a failed or incomplete transaction with a possible balance deduction",
    CaseType.REFUND_REQUEST: "requesting a refund for a previous transaction",
    CaseType.DUPLICATE_PAYMENT: "being charged twice for the same payment",
    CaseType.MERCHANT_SETTLEMENT_DELAY: "a delay in merchant settlement",
    CaseType.AGENT_CASH_IN_ISSUE: "an issue with agent cash-in service",
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING: "a suspected phishing or social engineering attempt",
    CaseType.OTHER: "a general support inquiry",
}

_NEXT_ACTIONS: dict[CaseType, str] = {
    CaseType.WRONG_TRANSFER: (
        "Verify the transaction details with the customer and initiate "
        "the dispute resolution process through official channels."
    ),
    CaseType.PAYMENT_FAILED: (
        "Check the transaction status in the system. If the balance was "
        "deducted without completion, escalate to payments operations."
    ),
    CaseType.REFUND_REQUEST: (
        "Review the referenced transaction and verify eligibility for "
        "resolution through the standard dispute workflow."
    ),
    CaseType.DUPLICATE_PAYMENT: (
        "Verify both charges in the system and escalate to payments "
        "operations for duplicate transaction investigation."
    ),
    CaseType.MERCHANT_SETTLEMENT_DELAY: (
        "Check the settlement schedule and merchant account status. "
        "Escalate to merchant operations if settlement is overdue."
    ),
    CaseType.AGENT_CASH_IN_ISSUE: (
        "Verify the cash-in transaction with the agent point records "
        "and escalate to agent operations for reconciliation."
    ),
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING: (
        "Flag this case for immediate fraud risk review. Advise the "
        "customer to secure their account through official channels."
    ),
    CaseType.OTHER: (
        "Review the complaint details and gather additional information "
        "from the customer to properly classify and route this case."
    ),
}

_CUSTOMER_REPLIES: dict[CaseType, str] = {
    CaseType.WRONG_TRANSFER: (
        "We have received your concern regarding a transaction to an "
        "unintended recipient. Our team is reviewing the details. "
        "Any eligible amount will be returned through official channels. "
        "Please do not share your PIN or OTP with anyone. "
        "For updates, please contact our official support."
    ),
    CaseType.PAYMENT_FAILED: (
        "We understand your concern about an incomplete transaction. "
        "Our payments team is investigating the matter. "
        "If any amount was incorrectly deducted, eligible adjustments "
        "will be processed through official channels. "
        "Please contact our official support for further assistance."
    ),
    CaseType.REFUND_REQUEST: (
        "Thank you for reaching out regarding your refund request. "
        "Our team will review the transaction and its eligibility. "
        "Any eligible amount will be returned through official channels. "
        "Please contact our official support for status updates."
    ),
    CaseType.DUPLICATE_PAYMENT: (
        "We have noted your concern about a possible duplicate charge. "
        "Our payments team is reviewing the transactions involved. "
        "If a duplicate is confirmed, the eligible amount will be "
        "returned through official channels. "
        "Please contact our official support for updates."
    ),
    CaseType.MERCHANT_SETTLEMENT_DELAY: (
        "We understand your concern about a settlement delay. "
        "Our merchant operations team is reviewing your case. "
        "Settlement adjustments, if applicable, will be processed "
        "through official channels. Please contact our official "
        "support for further information."
    ),
    CaseType.AGENT_CASH_IN_ISSUE: (
        "We have received your report regarding a cash-in issue. "
        "Our team is investigating the matter with the relevant "
        "agent point. Any eligible adjustment will be made through "
        "official channels. Please contact our official support "
        "for updates."
    ),
    CaseType.PHISHING_OR_SOCIAL_ENGINEERING: (
        "Thank you for reporting this suspicious activity. "
        "Please do NOT share your PIN, OTP, or password with anyone. "
        "Our fraud prevention team is reviewing this case. "
        "For your security, please contact our official support "
        "channels immediately if you have shared any sensitive "
        "information."
    ),
    CaseType.OTHER: (
        "Thank you for contacting us. We have noted your concern "
        "and our team will review it shortly. Please contact our "
        "official support channels for further assistance."
    ),
}


# ── Classification ───────────────────────────────────────────────────────────


def _classify_case_type(complaint: str) -> CaseType:
    """Classify the complaint into a CaseType using keyword matching."""
    text = complaint.lower()
    for case_type, keywords in _CASE_TYPE_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return case_type
    return CaseType.OTHER


# ── Transaction Matching ─────────────────────────────────────────────────────


def _find_relevant_transaction(
    case_type: CaseType,
    transactions: Optional[List[TransactionHistory]],
) -> Optional[str]:
    """Find the most relevant transaction ID for the given case type."""
    if not transactions:
        return None

    if case_type == CaseType.WRONG_TRANSFER:
        for txn in transactions:
            if txn.type.value == "transfer" and txn.status.value == "completed":
                return txn.transaction_id

    elif case_type == CaseType.PAYMENT_FAILED:
        for txn in transactions:
            if txn.status.value in ("failed", "pending"):
                return txn.transaction_id
        # Also check completed where balance might have been deducted
        for txn in transactions:
            if txn.type.value == "payment":
                return txn.transaction_id

    elif case_type == CaseType.DUPLICATE_PAYMENT:
        amounts = Counter(txn.amount for txn in transactions)
        for amount, count in amounts.items():
            if count >= 2:
                for txn in transactions:
                    if txn.amount == amount:
                        return txn.transaction_id

    elif case_type == CaseType.REFUND_REQUEST:
        for txn in transactions:
            if txn.status.value == "completed":
                return txn.transaction_id

    elif case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        for txn in transactions:
            if txn.type.value == "settlement":
                return txn.transaction_id

    elif case_type == CaseType.AGENT_CASH_IN_ISSUE:
        for txn in transactions:
            if txn.type.value == "cash_in":
                return txn.transaction_id

    # Fallback: return first transaction
    return transactions[0].transaction_id if transactions else None


def _determine_verdict(
    transactions: Optional[List[TransactionHistory]],
    relevant_txn_id: Optional[str],
) -> EvidenceVerdict:
    """Determine evidence verdict based on transaction matching."""
    if not transactions:
        return EvidenceVerdict.INSUFFICIENT_DATA
    if relevant_txn_id:
        return EvidenceVerdict.CONSISTENT
    return EvidenceVerdict.INCONSISTENT


# ── Public Entry Point ───────────────────────────────────────────────────────


def analyze_ticket_rule_based(request: TicketRequest) -> TicketResponse:
    """
    Analyze a ticket using deterministic rule-based logic.

    This is the fallback when LLM analysis is unavailable.
    """
    case_type = _classify_case_type(request.complaint)
    department = _CASE_TO_DEPARTMENT[case_type]
    severity = _CASE_TO_SEVERITY[case_type]

    relevant_txn_id = _find_relevant_transaction(
        case_type, request.transaction_history
    )
    verdict = _determine_verdict(request.transaction_history, relevant_txn_id)

    # Build evidence description for the summary
    if verdict == EvidenceVerdict.CONSISTENT:
        evidence_info = (
            f"Transaction {relevant_txn_id} in the history supports this report"
        )
    elif verdict == EvidenceVerdict.INCONSISTENT:
        evidence_info = (
            "Transaction history does not clearly support the reported issue"
        )
    else:
        evidence_info = "No transaction history was provided for verification"

    description = _CASE_DESCRIPTIONS[case_type]
    agent_summary = (
        f"Customer reports {description}. {evidence_info}."
    )

    reason_codes: List[str] = [case_type.value]
    if relevant_txn_id:
        reason_codes.append("transaction_match")
    if verdict == EvidenceVerdict.INCONSISTENT:
        reason_codes.append("evidence_mismatch")
    if verdict == EvidenceVerdict.INSUFFICIENT_DATA:
        reason_codes.append("no_transaction_data")

    human_review = severity in (Severity.HIGH, Severity.CRITICAL)

    logger.info(
        "Rule-based analysis for ticket %s: case_type=%s, severity=%s",
        request.ticket_id,
        case_type.value,
        severity.value,
    )

    return TicketResponse(
        ticket_id=request.ticket_id,
        relevant_transaction_id=relevant_txn_id,
        evidence_verdict=verdict,
        case_type=case_type,
        severity=severity,
        department=department,
        agent_summary=agent_summary,
        recommended_next_action=_NEXT_ACTIONS[case_type],
        customer_reply=_CUSTOMER_REPLIES[case_type],
        human_review_required=human_review,
        confidence=0.60,
        reason_codes=reason_codes,
    )
