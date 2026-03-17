"""Feedback module for logging suggestions and user feedback."""

from app.feedback.logger import (
    setup_feedback_table,
    log_suggestion,
    log_suggestions_batch,
    record_user_feedback,
    get_suggestion_analytics
)

__all__ = [
    "setup_feedback_table",
    "log_suggestion",
    "log_suggestions_batch",
    "record_user_feedback",
    "get_suggestion_analytics",
]
