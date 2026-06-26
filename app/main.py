"""
Support Copilot API – FastAPI application entry point.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.llm_service import analyze_ticket_with_llm
from app.models import (
    ErrorResponse,
    HealthResponse,
    TicketRequest,
    TicketResponse,
)
from app.rule_engine import analyze_ticket_rule_based
from app.safety import safety_check

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    llm_status = "configured ✓" if settings.OPENROUTER_API_KEY else "NOT configured (rule-based fallback only)"
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("LLM backend: %s (%s)", settings.LLM_MODEL, llm_status)
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI-powered Support Copilot that investigates customer complaints, "
        "cross-references transaction history, and routes cases to the "
        "appropriate department with safe customer replies."
    ),
    lifespan=lifespan,
)


# ── Exception Handlers ──────────────────────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    """Return 422 for schema validation errors."""
    errors = exc.errors()
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in errors
    )
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="Validation error",
            detail=detail,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Return 500 without stack traces or secrets."""
    logger.exception("Unhandled exception: %s", str(exc))
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail="An unexpected error occurred. Please try again later.",
        ).model_dump(),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["System"],
)
async def health():
    """Returns service health status."""
    return HealthResponse()


@app.post(
    "/analyze-ticket",
    response_model=TicketResponse,
    summary="Analyze a customer support ticket",
    tags=["Analysis"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid JSON or missing fields"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def analyze_ticket(request: TicketRequest):
    """
    Analyze a customer support ticket.

    The service will:
    1. Attempt LLM-based analysis (if OpenRouter API key is configured)
    2. Fall back to rule-based analysis if LLM is unavailable or fails
    3. Apply safety checks to the response before returning
    """
    response: TicketResponse | None = None

    # Try LLM first
    if settings.OPENROUTER_API_KEY:
        logger.info("Attempting LLM analysis for ticket %s", request.ticket_id)
        response = await analyze_ticket_with_llm(request)

    # Fallback to rule-based
    if response is None:
        logger.info(
            "Using rule-based analysis for ticket %s", request.ticket_id
        )
        response = analyze_ticket_rule_based(request)

    # Safety check
    response = safety_check(response)

    return response
