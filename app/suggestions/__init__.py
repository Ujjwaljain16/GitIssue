"""Suggestions module: duplicate detection engine and comment bot."""

from app.suggestions.engine import suggest_duplicates
from app.suggestions.bot import (
    setup_bot_comments_table,
    has_comment,
    record_comment,
    format_suggestion_comment,
    maybe_comment_with_suggestions
)

__all__ = [
    "suggest_duplicates",
    "setup_bot_comments_table",
    "has_comment",
    "record_comment",
    "format_suggestion_comment",
    "maybe_comment_with_suggestions",
]
