from sqlalchemy.orm import Session
from sqlalchemy import and_, func, extract
from typing import Dict, List, Optional
from decimal import Decimal

from app.models.transaction import Transaction, TransactionType
from app.models.account import Account
from app.models.category import Category

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class CategoryExpensesService:
    def __init__(self, db: Session):
        self.db = db

    def get_category_expenses_monthly(self, account_ids: list[int], year: int) -> Dict:
        if not account_ids:
            return {
                "year": year,
                "categories": [],
                "months": [
                    {"month": m, "label": MONTH_LABELS[m - 1], "categories": {}, "total": 0.0}
                    for m in range(1, 13)
                ],
                "grand_total": 0.0,
            }
        rows = (
            self.db.query(
                extract("month", Transaction.transaction_date).label("month"),
                Transaction.category_id,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Account, Transaction.account_id == Account.id)
            .filter(
                and_(
                    Transaction.account_id.in_(account_ids),
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    extract("year", Transaction.transaction_date) == year,
                )
            )
            .group_by(
                extract("month", Transaction.transaction_date),
                Transaction.category_id,
            )
            .all()
        )

        # Build lookup: category_id -> {name, color}
        category_ids = {r.category_id for r in rows if r.category_id is not None}
        cat_map: Dict[Optional[int], Dict] = {}
        if category_ids:
            cats = (
                self.db.query(Category)
                .filter(Category.id.in_(category_ids))
                .all()
            )
            for c in cats:
                cat_map[c.id] = {"id": c.id, "name": c.name, "color": c.color or "#6B7280"}

        # Accumulate totals per category and per (month, category)
        annual_totals: Dict[Optional[int], Decimal] = {}
        month_cat: Dict[int, Dict[Optional[int], Decimal]] = {m: {} for m in range(1, 13)}

        for r in rows:
            month = int(r.month)
            cat_id = r.category_id
            amount = r.total or Decimal(0)

            annual_totals[cat_id] = annual_totals.get(cat_id, Decimal(0)) + amount
            month_cat[month][cat_id] = amount

        # Sort categories by annual total descending
        sorted_cat_ids = sorted(annual_totals.keys(), key=lambda cid: annual_totals[cid], reverse=True)

        # Build categories list
        categories: List[Dict] = []
        cat_name_map: Dict[Optional[int], str] = {}
        for cat_id in sorted_cat_ids:
            if cat_id is not None and cat_id in cat_map:
                info = cat_map[cat_id]
                categories.append({"id": info["id"], "name": info["name"], "color": info["color"]})
                cat_name_map[cat_id] = info["name"]
            else:
                categories.append({"id": None, "name": "Uncategorized", "color": "#6B7280"})
                cat_name_map[cat_id] = "Uncategorized"

        # Build months array (always 12)
        grand_total = Decimal(0)
        months: List[Dict] = []
        for m in range(1, 13):
            cat_amounts = month_cat[m]
            month_total = Decimal(0)
            cat_dict: Dict[str, float] = {}
            for cat_id in sorted_cat_ids:
                if cat_id in cat_amounts:
                    val = cat_amounts[cat_id]
                    cat_dict[cat_name_map[cat_id]] = float(val)
                    month_total += val
            grand_total += month_total
            months.append({
                "month": m,
                "label": MONTH_LABELS[m - 1],
                "categories": cat_dict,
                "total": float(month_total),
            })

        return {
            "year": year,
            "categories": categories,
            "months": months,
            "grand_total": float(grand_total),
        }
