"""
Splitwise API Service

Wrapper around the Splitwise SDK for creating expenses and managing friends.
Uses API key authentication (simpler than OAuth2 for self-hosted apps).
"""

from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.user import ExpenseUser
from typing import List, Dict, Optional
from decimal import Decimal
from datetime import datetime


class SplitwiseService:
    """Service for interacting with Splitwise API"""

    def __init__(self, api_key: str):
        """
        Initialize Splitwise client with API key.

        Args:
            api_key: Splitwise API key (get from https://secure.splitwise.com/apps)
        """
        self.client = Splitwise(
            consumer_key=None,  # Not needed for API key auth
            consumer_secret=None,
            api_key=api_key,
        )

    def get_current_user(self) -> Dict:
        """
        Get current Splitwise user info (for credential verification).

        Returns:
            Dict with user info: id, first_name, last_name, email

        Raises:
            Exception: If API key is invalid or API call fails
        """
        user = self.client.getCurrentUser()
        return {
            "id": user.getId(),
            "first_name": user.getFirstName(),
            "last_name": user.getLastName(),
            "email": user.getEmail(),
        }

    def get_friends(self) -> List[Dict]:
        """
        Get list of Splitwise friends.

        Returns:
            List of friend dictionaries with id, name, email, and balance info
        """
        friends = self.client.getFriends()
        return [
            {
                "id": friend.getId(),
                "first_name": friend.getFirstName(),
                "last_name": friend.getLastName(),
                "email": friend.getEmail(),
                "balance": self._get_balance_list(friend.getBalances()),
            }
            for friend in friends
        ]

    def get_groups(self) -> List[Dict]:
        """
        Get list of Splitwise groups the user belongs to.

        Returns:
            List of group dictionaries with id, name, and members list
        """
        groups = self.client.getGroups()
        result = []
        for group in groups:
            # Skip the special "Non-group expenses" group (always id=0)
            if group.getId() == 0:
                continue
            members = group.getMembers() or []
            result.append(
                {
                    "id": group.getId(),
                    "name": group.getName(),
                    "members": [
                        {
                            "id": m.getId(),
                            "first_name": m.getFirstName(),
                            "last_name": m.getLastName(),
                            "email": m.getEmail(),
                        }
                        for m in members
                    ],
                }
            )
        return result

    def create_expense(
        self,
        description: str,
        amount: Decimal,
        currency: str,
        date: datetime,
        split_type: str,
        participants: List[Dict],
        notes: Optional[str] = None,
        group_id: Optional[int] = None,
    ) -> Dict:
        """
        Create a Splitwise expense with custom split configuration.

        Args:
            description: Expense description
            amount: Total expense amount
            currency: Currency code (USD, EUR, etc.)
            date: Transaction date
            split_type: How to split - "equal", "exact", or "percent"
            participants: List of users with their shares
                Format: [{"user_id": 123, "owed_share": 25.00, "paid_share": 0}]
            notes: Optional notes to attach to expense

        Returns:
            Dict with created expense info: id, description, cost, date, url

        Raises:
            Exception: If expense creation fails
        """
        expense = Expense()
        expense.setCost(str(amount))
        expense.setDescription(description)
        expense.setDate(date.strftime("%Y-%m-%d"))
        expense.setCurrencyCode(currency)

        if notes:
            expense.setDetails(notes)

        if group_id:
            expense.setGroupId(group_id)

        # Configure split type
        if split_type == "equal":
            expense.setSplitEqually(True)
        else:
            expense.setSplitEqually(False)

        # Add participants with their share amounts
        users = []
        for participant in participants:
            user = ExpenseUser()
            user.setId(participant["user_id"])
            user.setOwedShare(str(participant["owed_share"]))
            user.setPaidShare(str(participant.get("paid_share", 0)))
            users.append(user)

        expense.setUsers(users)

        # Create expense via API.
        # Newer SDK versions return a (Expense, Errors) tuple; older ones return
        # the Expense object directly.
        result = self.client.createExpense(expense)

        if isinstance(result, tuple):
            created_expense, errors = result
        else:
            created_expense = result
            errors = created_expense.getErrors() if hasattr(created_expense, "getErrors") else None

        if errors:
            messages = []
            errors_dict = errors.__dict__ if hasattr(errors, "__dict__") else {}
            for field, value in errors_dict.items():
                if isinstance(value, list):
                    messages.extend([str(m) for m in value if m])
                elif value:
                    messages.append(str(value))
            raise Exception("; ".join(messages) if messages else "Splitwise returned an unknown error")

        return {
            "id": created_expense.getId(),
            "description": created_expense.getDescription(),
            "cost": created_expense.getCost(),
            "date": created_expense.getDate(),
            "url": f"https://secure.splitwise.com/expenses/{created_expense.getId()}",
        }

    def _get_balance_list(self, balances) -> List[Dict]:
        """
        Parse Splitwise balance objects into dictionaries.

        Args:
            balances: Balance objects from Splitwise SDK

        Returns:
            List of balance dicts with currency_code and amount
        """
        if not balances:
            return []
        return [
            {
                "currency_code": balance.getCurrencyCode(),
                "amount": float(balance.getAmount()),
            }
            for balance in balances
        ]
