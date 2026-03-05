"""
Parser management API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.schemas.parser import (
    ParserMetadata,
    ParserDetectionResponse,
    ParserDetectionResult,
)
from app.services.csv_import import registry

router = APIRouter()


@router.get("/", response_model=List[ParserMetadata])
async def list_parsers(
    current_user: User = Depends(get_current_user),
):
    """
    List all available CSV parsers with their metadata.

    Returns:
        List[ParserMetadata]: Available parsers
    """
    parsers = registry.list_parsers()
    return parsers


@router.post("/detect", response_model=ParserDetectionResponse)
async def detect_parser(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Auto-detect which parser matches the uploaded CSV or PDF file.

    Args:
        file: CSV or PDF file to analyze

    Returns:
        ParserDetectionResponse: Detection results with confidence scores
    """
    # Validate file type - accept CSV and PDF
    if not file.filename or not (file.filename.endswith(".csv") or file.filename.endswith(".pdf")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV (.csv) or PDF (.pdf) file"
        )

    # Read file content
    try:
        content = await file.read()

        # For CSV files, decode as UTF-8 string
        # For PDF files, keep as bytes
        if file.filename.endswith(".csv"):
            try:
                file_content = content.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="CSV file encoding error. Please ensure the file is UTF-8 encoded."
                )
        else:  # PDF
            file_content = content

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error reading file: {str(e)}"
        )

    # Detect parser
    detected = registry.detect_parser(file_content, min_confidence=0.3)

    if not detected:
        return ParserDetectionResponse(
            detected=None,
            confidence=0.0,
            alternatives=[]
        )

    # Best match
    best_match = detected[0]
    alternatives = [
        ParserDetectionResult(name=name, confidence=conf)
        for name, conf in detected[1:]
    ]

    return ParserDetectionResponse(
        detected=best_match[0],
        confidence=best_match[1],
        alternatives=alternatives
    )
