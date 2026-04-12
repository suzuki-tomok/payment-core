"""Stripe API モックのヘルパー."""

from unittest.mock import MagicMock


def mock_checkout_session(payment_intent_id: str, price_id: str) -> MagicMock:
    """checkout.Session.retrieve のモックレスポンスを作成（クレジット用）."""
    mock_line_item = MagicMock()
    mock_line_item.price.id = price_id
    mock_session = MagicMock()
    mock_session.payment_intent = payment_intent_id
    mock_session.line_items.data = [mock_line_item]
    return mock_session


def mock_checkout_session_custom(payment_intent_id: str, description: str, amount: int) -> MagicMock:
    """checkout.Session.retrieve のモックレスポンスを作成（カスタム支払い用）."""
    mock_line_item = MagicMock()
    mock_line_item.description = description
    mock_line_item.amount_total = amount
    mock_session = MagicMock()
    mock_session.payment_intent = payment_intent_id
    mock_session.line_items.data = [mock_line_item]
    return mock_session


def mock_subscription(price_id: str, period_start: int, period_end: int) -> dict:  # type: ignore[type-arg]
    """Subscription.retrieve のモックレスポンスを作成."""
    return {
        "items": {"data": [{
            "price": {"id": price_id},
            "current_period_start": period_start,
            "current_period_end": period_end,
        }]},
        "status": "active",
    }
