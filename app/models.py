"""
Pydantic models, enums, and schemas for the Support Copilot API.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class Language(str, Enum):
    EN = "en"
    BN = "bn"
    MIXED = "mixed"


class Channel(str, Enum):
    IN_APP_CHAT = "in_app_chat"
    CALL_CENTER = "call_center"
    EMAIL = "email"
    MERCHANT_PORTAL = "merchant_portal"
    FIELD_AGENT = "field_agent"


class UserType(str, Enum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    AGENT = "agent"
    UNKNOWN = "unknown"


class TransactionType(str, Enum):
    TRANSFER = "transfer"
    PAYMENT = "payment"
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    SETTLEMENT = "settlement"
    REFUND = "refund"


class TransactionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
    REVERSED = "reversed"


class EvidenceVerdict(str, Enum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    INSUFFICIENT_DATA = "insufficient_data"


class CaseType(str, Enum):
    WRONG_TRANSFER = "wrong_transfer"
    PAYMENT_FAILED = "payment_failed"
    REFUND_REQUEST = "refund_request"
    DUPLICATE_PAYMENT = "duplicate_payment"
    MERCHANT_SETTLEMENT_DELAY = "merchant_settlement_delay"
    AGENT_CASH_IN_ISSUE = "agent_cash_in_issue"
    PHISHING_OR_SOCIAL_ENGINEERING = "phishing_or_social_engineering"
    OTHER = "other"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Department(str, Enum):
    CUSTOMER_SUPPORT = "customer_support"
    DISPUTE_RESOLUTION = "dispute_resolution"
    PAYMENTS_OPS = "payments_ops"
    MERCHANT_OPERATIONS = "merchant_operations"
    AGENT_OPERATIONS = "agent_operations"
    FRAUD_RISK = "fraud_risk"


# ── Request Models ───────────────────────────────────────────────────────────


class TransactionHistory(BaseModel):
    """A single transaction record from the customer's recent history."""

    transaction_id: str = Field(..., description="Unique transaction ID")
    timestamp: str = Field(..., description="ISO 8601 transaction timestamp")
    type: TransactionType = Field(..., description="Type of transaction")
    amount: float = Field(default=None, gt=0, description="Transaction amount in BDT")
    counterparty: str = Field(
        ..., description="Phone number, merchant ID, or agent ID"
    )
    status: TransactionStatus = Field(..., description="Transaction status")


class TicketRequest(BaseModel):
    """Incoming customer support ticket for analysis."""

    ticket_id: str = Field(..., description="Unique ticket identifier")
    complaint: str = Field(
        ..., min_length=1, description="Customer complaint text (en/bn/mixed)"
    )
    language: Optional[Language] = Field(
        default=Language.EN, description="Complaint language"
    )
    channel: Optional[Channel] = Field(
        default=None, description="Support channel"
    )
    user_type: Optional[UserType] = Field(
        default=UserType.CUSTOMER, description="Type of user filing the ticket"
    )
    campaign_context: Optional[str] = Field(
        default=None, description="Active campaign identifier"
    )
    transaction_history: Optional[List[TransactionHistory]] = Field(
        default=None, description="Recent transactions (2-5 records)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional context"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ticket_id": "TKT-001",
                    "complaint": "I sent 5000 taka to a wrong number around 2pm today...",
                    "language": "en",
                    "channel": "in_app_chat",
                    "user_type": "customer",
                    "campaign_context": "boishakh_bonanza_day_1",
                    "transaction_history": [
                        {
                            "transaction_id": "TXN-9101",
                            "timestamp": "2026-04-14T14:08:22Z",
                            "type": "transfer",
                            "amount": 5000,
                            "counterparty": "+8801719876543",
                            "status": "completed",
                        }
                    ],
                }
            ]
        }
    }


# ── Response Models ──────────────────────────────────────────────────────────


class TicketResponse(BaseModel):
    """Structured analysis result returned by the copilot."""

    ticket_id: str = Field(..., description="Echo of the request ticket ID")
    relevant_transaction_id: Optional[str] = Field(
        default=None, description="Transaction ID matching the complaint"
    )
    evidence_verdict: EvidenceVerdict = Field(
        ..., description="Investigation result from transaction cross-reference"
    )
    case_type: CaseType = Field(..., description="Classified complaint category")
    severity: Severity = Field(..., description="Urgency level")
    department: Department = Field(..., description="Assigned department for routing")
    agent_summary: str = Field(
        ..., description="1-2 sentence investigation summary for the agent"
    )
    recommended_next_action: str = Field(
        ..., description="Operational next step for the agent"
    )
    customer_reply: str = Field(
        ..., description="Safe customer-facing response"
    )
    human_review_required: bool = Field(
        ..., description="Whether escalation to a human is needed"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0-1)"
    )
    reason_codes: List[str] = Field(
        ..., description="Supporting reason labels"
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok")


class ErrorResponse(BaseModel):
    """Error response body."""

    error: str = Field(..., description="Error summary")
    detail: Optional[str] = Field(default=None, description="Additional detail")
