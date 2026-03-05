"""
Category suggestion service for auto-categorizing transactions.
"""
import re
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.category_rule import CategoryRule, PatternType


class CategorySuggester:
    """
    Suggests categories for transactions based on description patterns.

    Uses a combination of:
    1. User-defined rules from category_rules table
    2. Built-in pattern matching for common categories
    """

    # Built-in categorization patterns
    BUILTIN_PATTERNS = {
        "grocery": [
            "walmart", "target", "safeway", "whole foods", "trader joe", "kroger",
            "albertsons", "publix", "wegmans", "aldi", "costco", "sam's club",
            "food lion", "stop & shop", "giant", "harris teeter", "sprouts"
        ],
        "dining": [
            "restaurant", "cafe", "coffee", "starbucks", "dunkin", "mcdonald",
            "burger king", "taco bell", "chipotle", "panera", "subway",
            "doordash", "uber eats", "grubhub", "postmates", "seamless"
        ],
        "gas": [
            "shell", "chevron", "exxon", "bp", "mobil", "citgo", "marathon",
            "sunoco", "valero", "gas station", "fuel", "76"
        ],
        "transport": [
            "uber", "lyft", "taxi", "parking", "metro", "transit", "bus",
            "subway", "train", "toll", "parking garage", "valet"
        ],
        "utilities": [
            "electric", "gas company", "water", "internet", "comcast", "at&t",
            "verizon", "spectrum", "phone bill", "cell phone", "mobile",
            "xfinity", "frontier", "century link"
        ],
        "entertainment": [
            "netflix", "spotify", "hulu", "disney", "hbo", "amazon prime",
            "apple music", "youtube", "movie", "cinema", "theater", "concert",
            "ticketmaster", "live nation", "steam", "playstation", "xbox"
        ],
        "shopping": [
            "amazon", "ebay", "etsy", "best buy", "apple store", "walmart.com",
            "target.com", "macy", "nordstrom", "gap", "old navy", "tj maxx",
            "marshalls", "homegoods", "ikea", "home depot", "lowes"
        ],
        "health": [
            "pharmacy", "cvs", "walgreens", "rite aid", "doctor", "hospital",
            "medical", "dental", "dentist", "clinic", "urgent care", "lab corp",
            "quest diagnostic", "health insurance", "gym", "fitness"
        ],
        "travel": [
            "airline", "hotel", "airbnb", "vrbo", "expedia", "booking.com",
            "kayak", "united", "delta", "american airlines", "southwest",
            "marriott", "hilton", "hyatt", "rental car", "hertz", "enterprise"
        ]
    }

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._user_rules = None
        self._user_categories = None

    def _load_user_rules(self):
        """Load and cache user's category rules."""
        if self._user_rules is None:
            self._user_rules = (
                self.db.query(CategoryRule)
                .filter(
                    CategoryRule.user_id == self.user_id,
                    CategoryRule.is_active == True
                )
                .order_by(CategoryRule.priority.desc())
                .all()
            )

    def _load_user_categories(self):
        """Load and cache user's categories."""
        if self._user_categories is None:
            categories = (
                self.db.query(Category)
                .filter(Category.user_id == self.user_id)
                .all()
            )
            # Create lookup dict by lowercase name
            self._user_categories = {
                cat.name.lower(): cat for cat in categories
            }

    def suggest_category(self, description: str) -> Optional[Tuple[int, str, float]]:
        """
        Suggest category for a transaction description.

        Args:
            description: Transaction description

        Returns:
            Optional[Tuple[int, str, float]]: (category_id, category_name, confidence)
            Returns None if no match found
        """
        desc_lower = description.lower()

        # 1. Check user-defined rules first (highest priority)
        self._load_user_rules()
        for rule in self._user_rules:
            if self._matches_rule(desc_lower, rule):
                category = self.db.query(Category).get(rule.category_id)
                if category:
                    return (category.id, category.name, 1.0)

        # 2. Check built-in patterns
        self._load_user_categories()
        for category_name, keywords in self.BUILTIN_PATTERNS.items():
            for keyword in keywords:
                if keyword in desc_lower:
                    # Try to find matching category in user's categories
                    user_category = self._user_categories.get(category_name)
                    if user_category:
                        return (user_category.id, user_category.name, 0.8)

        return None

    def _matches_rule(self, description: str, rule: CategoryRule) -> bool:
        """
        Check if description matches a category rule.

        Args:
            description: Lowercase transaction description
            rule: Category rule to check

        Returns:
            bool: True if matches, False otherwise
        """
        pattern = rule.pattern.lower()

        if rule.pattern_type == PatternType.EXACT:
            return description == pattern

        elif rule.pattern_type == PatternType.KEYWORD:
            return pattern in description

        elif rule.pattern_type == PatternType.REGEX:
            try:
                return bool(re.search(pattern, description))
            except re.error:
                # Invalid regex, treat as keyword
                return pattern in description

        return False

    def suggest_batch(
        self, descriptions: List[str]
    ) -> List[Optional[Tuple[int, str, float]]]:
        """
        Suggest categories for multiple transactions at once.

        Args:
            descriptions: List of transaction descriptions

        Returns:
            List of suggestions (same length as input)
        """
        return [self.suggest_category(desc) for desc in descriptions]

    def create_rule_from_pattern(
        self,
        category_id: int,
        pattern: str,
        pattern_type: PatternType = PatternType.KEYWORD,
        priority: int = 0
    ) -> CategoryRule:
        """
        Create a new category rule.

        Args:
            category_id: Category to assign
            pattern: Pattern to match
            pattern_type: Type of pattern matching
            priority: Priority (higher = checked first)

        Returns:
            CategoryRule: Created rule
        """
        rule = CategoryRule(
            user_id=self.user_id,
            category_id=category_id,
            pattern=pattern,
            pattern_type=pattern_type,
            priority=priority,
            is_active=True
        )
        self.db.add(rule)
        self.db.flush()

        # Invalidate cache
        self._user_rules = None

        return rule
