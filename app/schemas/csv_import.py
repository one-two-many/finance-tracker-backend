from pydantic import BaseModel
from typing import List, Optional


class TransactionImportResult(BaseModel):
    """Result for a single row in the CSV import"""
    row_number: int
    status: str  # "created", "skipped", "error"
    message: Optional[str] = None


class CSVImportResponse(BaseModel):
    """Summary response for CSV import operation"""
    total_rows: int
    created: int
    skipped: int
    errors: int
    results: List[TransactionImportResult]
    categories_created: List[str]
