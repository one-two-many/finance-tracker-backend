"""
CSV Import service with multi-parser support.

This module initializes all available CSV parsers and provides
the main interface for CSV import operations.
"""
from .parser_registry import registry
from .parsers import (
    AmexParser,
    DiscoverBankParser,
    DiscoverSavingsParser,
    ChaseBankParser,
    ChaseBankPDFParser,
)

# Legacy imports for backwards compatibility
from .legacy import (
    is_duplicate,
    find_or_create_category,
    parse_amex_csv,
)


def initialize_parsers():
    """
    Register all available parsers with the global registry.
    This function is called on module import.
    """
    parsers = [
        AmexParser(),
        DiscoverBankParser(),
        DiscoverSavingsParser(),
        ChaseBankParser(),
        ChaseBankPDFParser(),
    ]

    for parser in parsers:
        registry.register(parser)


# Initialize parsers on module import
initialize_parsers()


__all__ = [
    "registry",
    "is_duplicate",
    "find_or_create_category",
    "parse_amex_csv",
]
