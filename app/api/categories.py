"""
Category and category rules API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.category import Category
from app.models.category_rule import CategoryRule, PatternType

router = APIRouter()


# Schemas
class CategoryResponse(BaseModel):
    id: int
    name: str
    color: str
    icon: str

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str
    color: str = "#6366f1"
    icon: str = "💰"


class CategoryUpdate(BaseModel):
    name: str = None
    color: str = None
    icon: str = None


class CategoryRuleCreate(BaseModel):
    category_id: int
    pattern: str
    pattern_type: str = "keyword"
    priority: int = 0


class CategoryRuleResponse(BaseModel):
    id: int
    category_id: int
    category_name: str
    pattern: str
    pattern_type: str
    priority: int
    is_active: bool

    class Config:
        from_attributes = True


class CategoryRuleUpdate(BaseModel):
    pattern: str = None
    pattern_type: str = None
    priority: int = None
    is_active: bool = None


@router.get("/", response_model=List[CategoryResponse])
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all categories for the current user.

    Returns:
        List[CategoryResponse]: User's categories
    """
    categories = (
        db.query(Category)
        .filter(Category.user_id == current_user.id)
        .order_by(Category.name)
        .all()
    )

    return categories


@router.post("/", response_model=CategoryResponse)
async def create_category(
    category_data: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new category.

    Args:
        category_data: Category creation data

    Returns:
        CategoryResponse: Created category
    """
    # Check if category with same name already exists
    existing = db.query(Category).filter(
        Category.user_id == current_user.id,
        Category.name == category_data.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{category_data.name}' already exists"
        )

    # Create category
    category = Category(
        user_id=current_user.id,
        name=category_data.name,
        color=category_data.color,
        icon=category_data.icon
    )

    db.add(category)
    db.commit()
    db.refresh(category)

    return category


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    category_data: CategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an existing category.

    Args:
        category_id: Category ID to update
        category_data: Updated category data

    Returns:
        CategoryResponse: Updated category
    """
    # Get category
    category = db.query(Category).filter(
        Category.id == category_id,
        Category.user_id == current_user.id
    ).first()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found or you don't have permission to access it"
        )

    # Check for name conflicts if name is being changed
    if category_data.name and category_data.name != category.name:
        existing = db.query(Category).filter(
            Category.user_id == current_user.id,
            Category.name == category_data.name
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category '{category_data.name}' already exists"
            )

    # Update fields
    if category_data.name is not None:
        category.name = category_data.name

    if category_data.color is not None:
        category.color = category_data.color

    if category_data.icon is not None:
        category.icon = category_data.icon

    db.commit()
    db.refresh(category)

    return category


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a category.

    Args:
        category_id: Category ID to delete

    Returns:
        dict: Success message
    """
    # Get category
    category = db.query(Category).filter(
        Category.id == category_id,
        Category.user_id == current_user.id
    ).first()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found or you don't have permission to access it"
        )

    # Check if category is in use by transactions
    from app.models.transaction import Transaction
    transaction_count = db.query(Transaction).filter(
        Transaction.category_id == category_id
    ).count()

    if transaction_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete category. It is used by {transaction_count} transaction(s). Please reassign or delete those transactions first."
        )

    # Delete associated rules
    db.query(CategoryRule).filter(
        CategoryRule.category_id == category_id
    ).delete()

    # Delete category
    db.delete(category)
    db.commit()

    return {"message": "Category deleted successfully"}


@router.get("/rules", response_model=List[CategoryRuleResponse])
async def list_category_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all category rules for the current user.

    Returns:
        List[CategoryRuleResponse]: User's category rules
    """
    rules = (
        db.query(CategoryRule)
        .join(Category)
        .filter(CategoryRule.user_id == current_user.id)
        .order_by(CategoryRule.priority.desc(), CategoryRule.created_at.desc())
        .all()
    )

    # Manually construct response with category name
    result = []
    for rule in rules:
        category = db.query(Category).get(rule.category_id)
        result.append(CategoryRuleResponse(
            id=rule.id,
            category_id=rule.category_id,
            category_name=category.name if category else "Unknown",
            pattern=rule.pattern,
            pattern_type=rule.pattern_type.value,
            priority=rule.priority,
            is_active=rule.is_active
        ))

    return result


@router.post("/rules", response_model=CategoryRuleResponse)
async def create_category_rule(
    rule_data: CategoryRuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new category rule.

    Args:
        rule_data: Rule creation data

    Returns:
        CategoryRuleResponse: Created rule
    """
    # Verify category exists and belongs to user
    category = db.query(Category).filter(
        Category.id == rule_data.category_id,
        Category.user_id == current_user.id
    ).first()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found or you don't have permission to access it"
        )

    # Validate pattern_type
    try:
        pattern_type_enum = PatternType(rule_data.pattern_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid pattern_type. Must be one of: keyword, exact, regex"
        )

    # Create rule
    rule = CategoryRule(
        user_id=current_user.id,
        category_id=rule_data.category_id,
        pattern=rule_data.pattern,
        pattern_type=pattern_type_enum,
        priority=rule_data.priority,
        is_active=True
    )

    db.add(rule)
    db.commit()
    db.refresh(rule)

    return CategoryRuleResponse(
        id=rule.id,
        category_id=rule.category_id,
        category_name=category.name,
        pattern=rule.pattern,
        pattern_type=rule.pattern_type.value,
        priority=rule.priority,
        is_active=rule.is_active
    )


@router.patch("/rules/{rule_id}", response_model=CategoryRuleResponse)
async def update_category_rule(
    rule_id: int,
    rule_data: CategoryRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an existing category rule.

    Args:
        rule_id: Rule ID to update
        rule_data: Updated rule data

    Returns:
        CategoryRuleResponse: Updated rule
    """
    # Get rule
    rule = db.query(CategoryRule).filter(
        CategoryRule.id == rule_id,
        CategoryRule.user_id == current_user.id
    ).first()

    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found or you don't have permission to access it"
        )

    # Update fields
    if rule_data.pattern is not None:
        rule.pattern = rule_data.pattern

    if rule_data.pattern_type is not None:
        try:
            rule.pattern_type = PatternType(rule_data.pattern_type.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid pattern_type. Must be one of: keyword, exact, regex"
            )

    if rule_data.priority is not None:
        rule.priority = rule_data.priority

    if rule_data.is_active is not None:
        rule.is_active = rule_data.is_active

    db.commit()
    db.refresh(rule)

    category = db.query(Category).get(rule.category_id)

    return CategoryRuleResponse(
        id=rule.id,
        category_id=rule.category_id,
        category_name=category.name if category else "Unknown",
        pattern=rule.pattern,
        pattern_type=rule.pattern_type.value,
        priority=rule.priority,
        is_active=rule.is_active
    )


@router.delete("/rules/{rule_id}")
async def delete_category_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a category rule.

    Args:
        rule_id: Rule ID to delete

    Returns:
        dict: Success message
    """
    # Get rule
    rule = db.query(CategoryRule).filter(
        CategoryRule.id == rule_id,
        CategoryRule.user_id == current_user.id
    ).first()

    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found or you don't have permission to access it"
        )

    db.delete(rule)
    db.commit()

    return {"message": "Rule deleted successfully"}
