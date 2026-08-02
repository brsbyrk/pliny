"""Subscription routes — GET/POST/DELETE /api/subscriptions, notifications, SSE stream.

Note: Subscription functionality is planned but not yet implemented in the current
codebase. The module structure is prepared for future use.
"""

from fastapi import APIRouter

router = APIRouter()

# Subscription routes will be added here when the feature is implemented.
# Expected endpoints:
#   GET    /api/subscriptions
#   POST   /api/subscriptions
#   DELETE /api/subscriptions
#   GET    /api/subscriptions/notifications
#   POST   /api/subscriptions/ack
#   GET    /api/subscriptions/stream  (SSE StreamingResponse)
