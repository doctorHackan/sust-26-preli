"""
Post-processing safety checks for copilot responses.

Scans customer_reply and recommended_next_action for safety violations
and corrects them before the response is returned.
"""

from __future__ import annotations

import logging
import re
from typing import List

from app.models import TicketResponse

logger = logging.getLogger(__name__)

# ── Unsafe Patterns ──────────────────────────────────────────────────────────

# Rule 1: Never ask for sensitive credentials
# NOTE: Patterns must NOT match safe warnings like "do not share your PIN"
_SENSITIVE_INFO_PATTERNS: List[re.Pattern] = [
    # "please provide/share/send your PIN/OTP" (requesting)
    re.compile(r"\b(please\s+)?(provide|send|give|enter|tell|confirm)\s+(us\s+)?(your\s+)?(pin|otp|password|card\s*number)\b", re.IGNORECASE),
    # "share your PIN with us" (requesting) — but NOT "do not share"
    re.compile(r"(?<!\bnot\s)(?<!\bnever\s)\bshare\s+(your\s+)?(pin|otp|password|card\s*number)\b", re.IGNORECASE),
    # "what is your PIN" / "enter your OTP"
    re.compile(r"\b(what\s+is|enter|type|input)\s+(your\s+)?(pin|otp|password|card\s*number)\b", re.IGNORECASE),
    # "ask for PIN/OTP" — but NOT "never ask for"
    re.compile(r"(?<!\bnever\s)(?<!\bnot\s)\bask\s+(for\s+)?(your\s+)?(pin|otp|password|card\s*number)\b", re.IGNORECASE),
]

# Rule 2: Never promise refund/reversal/unblock
_PROMISE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bwe\s+will\s+(refund|reverse|unblock|recover)\b", re.IGNORECASE),
    re.compile(r"\byou\s+will\s+(get|receive)\s+(a\s+)?(refund|reversal)\b", re.IGNORECASE),
    re.compile(r"\b(guaranteed|promise|assured)\s+(refund|reversal|recovery)\b", re.IGNORECASE),
    re.compile(r"\byour\s+(money|amount|fund)\s+(will\s+be|has\s+been)\s+(refund|revers|return|recover)", re.IGNORECASE),
    re.compile(r"\bwe\s+(are|have)\s+(processing|processed|initiating|initiated)\s+(a\s+)?(refund|reversal)\b", re.IGNORECASE),
]

_SAFE_REFUND_PHRASE = (
    "Any eligible amount will be returned through official channels."
)
_SAFE_CREDENTIAL_PHRASE = (
    "Please do not share your PIN, OTP, or password with anyone."
)


def safety_check(response: TicketResponse) -> TicketResponse:
    """
    Inspect and sanitize the response for safety violations.

    If violations are found, the offending text is replaced with safe
    alternatives, human_review_required is set to True, and
    'safety_violation_corrected' is added to reason_codes.
    """
    violations_found = False
    data = response.model_dump()

    for field_name in ("customer_reply", "recommended_next_action"):
        text: str = data[field_name]

        # Check Rule 1 – sensitive info requests
        for pattern in _SENSITIVE_INFO_PATTERNS:
            if pattern.search(text):
                logger.warning(
                    "Safety violation (sensitive info request) in %s for ticket %s",
                    field_name,
                    response.ticket_id,
                )
                text = pattern.sub(_SAFE_CREDENTIAL_PHRASE, text)
                violations_found = True

        # Check Rule 2 – refund/reversal promises
        for pattern in _PROMISE_PATTERNS:
            if pattern.search(text):
                logger.warning(
                    "Safety violation (refund promise) in %s for ticket %s",
                    field_name,
                    response.ticket_id,
                )
                text = pattern.sub(_SAFE_REFUND_PHRASE, text)
                violations_found = True

        data[field_name] = text

    if violations_found:
        data["human_review_required"] = True
        if "safety_violation_corrected" not in data["reason_codes"]:
            data["reason_codes"].append("safety_violation_corrected")

    return TicketResponse.model_validate(data)
