from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal

from app.models.transaction import Transaction, TransactionType
from app.models.account import Account
from app.models.category import Category


class SankeyService:
    def __init__(self, db: Session):
        self.db = db

    def generate_sankey_data(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        include_transfers: bool = False
    ) -> Dict:
        """
        Generate Sankey diagram showing cash flow:
        Income Sources → Cash Flow (middle) → Expense Categories + Surplus

        Similar to the reference image with left (income), middle (cash flow), right (expenses + surplus)
        """
        nodes = []
        links = []
        node_names = set()

        # Helper to add unique nodes
        def add_node(name: str, node_type: str, color: Optional[str] = None):
            if name not in node_names:
                nodes.append({
                    "name": name,
                    "type": node_type,
                    "color": color
                })
                node_names.add(name)

        # Get all accounts for the user (we'll use for middle layer)
        accounts = self.db.query(Account).filter(Account.user_id == user_id).all()
        account_types = {acc.id: acc.account_type.value for acc in accounts}

        # Calculate total income (exclude credit card refunds)
        total_income = self.db.query(
            func.sum(Transaction.amount)
        ).join(
            Account, Transaction.account_id == Account.id
        ).filter(
            and_(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
                Account.account_type != "credit_card"
            )
        ).scalar() or Decimal(0)

        # Calculate total expenses
        total_expenses = self.db.query(
            func.sum(Transaction.amount)
        ).filter(
            and_(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).scalar() or Decimal(0)

        net_savings = float(total_income) - float(total_expenses)

        # === LEFT SIDE: Income Sources ===
        income_by_category = self.db.query(
            Transaction.category_id,
            func.sum(Transaction.amount).label("total")
        ).join(
            Account, Transaction.account_id == Account.id
        ).filter(
            and_(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
                Account.account_type != "credit_card"  # Exclude credit card refunds
            )
        ).group_by(Transaction.category_id).all()

        # Track income node names so expense nodes with the same name can be
        # disambiguated — duplicate names across the two sides create a cycle
        # (NodeX → Cash Flow → NodeX) that causes Sankey to recurse infinitely.
        income_node_names: set = set()
        # Reserve the names used by the middle/right special nodes
        reserved_names = {"Cash Flow", "Surplus"}

        for income in income_by_category:
            if income.category_id:
                category = self.db.query(Category).filter(Category.id == income.category_id).first()
                income_name = category.name if category else "Uncategorized Income"
                color = category.color if category else "#6B7280"
            else:
                income_name = "Uncategorized Income"
                color = "#6B7280"

            # Avoid collision with reserved middle/right node names
            if income_name in reserved_names:
                income_name = f"{income_name} (Income)"

            add_node(income_name, "income", color)
            income_node_names.add(income_name)

            # Link: Income Source → Cash Flow
            links.append({
                "source": income_name,
                "target": "Cash Flow",
                "value": float(income.total)
            })

        # === MIDDLE: Cash Flow ===
        add_node("Cash Flow", "cashflow", "#10B981")

        # === RIGHT SIDE: Expense Categories ===
        expense_by_category = self.db.query(
            Transaction.category_id,
            func.sum(Transaction.amount).label("total")
        ).filter(
            and_(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).group_by(Transaction.category_id).all()

        for expense in expense_by_category:
            if expense.category_id:
                category = self.db.query(Category).filter(Category.id == expense.category_id).first()
                expense_name = category.name if category else "Uncategorized"
                color = category.color if category else "#6B7280"
            else:
                expense_name = "Uncategorized"
                color = "#6B7280"

            # If this name was already used as an income node, qualify it to
            # prevent a cycle in the graph (income_name → Cash Flow → income_name)
            if expense_name in income_node_names or expense_name in reserved_names:
                expense_name = f"{expense_name} (Expenses)"

            add_node(expense_name, "expense", color)

            # Link: Cash Flow → Expense Category
            links.append({
                "source": "Cash Flow",
                "target": expense_name,
                "value": float(expense.total)
            })

        # === RIGHT SIDE: Surplus (if positive savings) ===
        if net_savings > 0:
            add_node("Surplus", "surplus", "#10B981")
            links.append({
                "source": "Cash Flow",
                "target": "Surplus",
                "value": net_savings
            })

        return {
            "nodes": nodes,
            "links": links,
            "summary": {
                "total_income": float(total_income),
                "total_expenses": float(total_expenses),
                "net_savings": net_savings,
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                }
            }
        }
