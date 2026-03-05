"""
Parser registry for managing and discovering CSV parsers.
"""
from typing import Dict, List, Optional, Tuple, Union
from .base_parser import CSVParser


class ParserRegistry:
    """
    Singleton registry for all CSV parsers.
    Handles parser registration and auto-detection.
    """
    _instance = None
    _parsers: Dict[str, CSVParser] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ParserRegistry, cls).__new__(cls)
            cls._instance._parsers = {}
        return cls._instance

    def register(self, parser: CSVParser) -> None:
        """
        Register a parser instance.

        Args:
            parser: Parser instance to register

        Raises:
            ValueError: If parser with same name already registered
        """
        parser_name = parser.get_name()
        if parser_name in self._parsers:
            raise ValueError(f"Parser '{parser_name}' is already registered")

        self._parsers[parser_name] = parser

    def get_parser(self, parser_name: str) -> Optional[CSVParser]:
        """
        Retrieve parser by name.

        Args:
            parser_name: Unique parser identifier

        Returns:
            Optional[CSVParser]: Parser instance or None if not found
        """
        return self._parsers.get(parser_name)

    def list_parsers(self) -> List[Dict]:
        """
        Get list of all registered parsers with metadata.

        Returns:
            List[Dict]: Parser metadata (name, display_name, type, required_headers)
        """
        return [
            {
                "name": parser.get_name(),
                "display_name": parser.get_display_name(),
                "parser_type": parser.get_parser_type(),
                "required_headers": parser.get_required_headers()
            }
            for parser in self._parsers.values()
        ]

    def detect_parser(self, content: Union[str, bytes], min_confidence: float = 0.5) -> List[Tuple[str, float]]:
        """
        Auto-detect which parser(s) match the file content.

        Args:
            content: Raw file content (str for CSV, bytes for PDF)
            min_confidence: Minimum confidence threshold (0.0-1.0)

        Returns:
            List[Tuple[str, float]]: List of (parser_name, confidence) sorted by confidence descending
        """
        results = []

        for parser in self._parsers.values():
            try:
                confidence = parser.detect(content)
                if confidence >= min_confidence:
                    results.append((parser.get_name(), confidence))
            except Exception:
                # If detection fails, skip this parser
                continue

        # Sort by confidence descending
        results.sort(key=lambda x: x[1], reverse=True)

        return results


# Global registry instance
registry = ParserRegistry()
