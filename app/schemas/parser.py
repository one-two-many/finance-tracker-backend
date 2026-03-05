"""
Schemas for parser API endpoints.
"""
from typing import List, Optional
from pydantic import BaseModel


class ParserMetadata(BaseModel):
    """Parser information for UI display."""
    name: str
    display_name: str
    parser_type: str
    required_headers: List[str]


class ParserDetectionResult(BaseModel):
    """Single parser detection result."""
    name: str
    confidence: float


class ParserDetectionResponse(BaseModel):
    """Response from parser detection endpoint."""
    detected: Optional[str]  # Best match parser name
    confidence: float
    alternatives: List[ParserDetectionResult]


class PreviewTransaction(BaseModel):
    """Preview of a single transaction before import."""
    date: str
    description: str
    amount: float
    original_amount: float  # Signed amount as it appears in CSV
    type: str
    suggested_category: Optional[str] = None
    is_duplicate: bool
    is_transfer_candidate: bool
    transfer_target_account: Optional[str] = None  # Name of target account for transfers
    transfer_target_account_id: Optional[int] = None  # ID of target account for transfers
    notes: Optional[str] = None


class TransferCandidate(BaseModel):
    """Potential transfer transaction."""
    description: str
    amount: float
    date: str


class ImportPreviewResponse(BaseModel):
    """Response from import preview endpoint."""
    parser_used: str
    parser_display_name: str
    confidence: float
    alternatives: List[ParserDetectionResult]
    total_transactions: int
    duplicate_count: int
    transfer_candidate_count: int
    transactions: List[PreviewTransaction]
    transfer_candidates: List[TransferCandidate]
    error: Optional[str] = None


class ImportConfirmRequest(BaseModel):
    """Request to confirm and execute import."""
    file_content: str
    account_id: int
    parser_name: str
    category_mappings: Optional[dict] = None  # description -> category_id
    type_overrides: Optional[dict] = None  # description -> transaction_type (income/expense/transfer/refund)
    skip_duplicates: bool = True
    filename: Optional[str] = None


class ImportConfirmResponse(BaseModel):
    """Response from import confirmation."""
    total_rows: int
    created: int
    skipped: int
    errors: int
    categories_created: List[str]
