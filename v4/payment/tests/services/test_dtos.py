"""CheckoutInput validation tests (DB 不要)."""

import pytest

from payment.services.dtos import CheckoutInput
from payment.services.exceptions import InvalidInputError


def _valid_kwargs() -> dict:
    """全 field 正常値のテンプレ."""
    return {
        "order_id": "order-1",
        "company_id": "company-1",
        "company_name": "Acme",
        "amount": 1000,
        "description": "Product",
        "success_url": "https://example.com/success?order_id=order-1",
        "cancel_url": "https://example.com/cancel?order_id=order-1",
    }


def test_valid_input_constructs():
    """全 field 正常値で構築成功."""
    dto = CheckoutInput(**_valid_kwargs())
    assert dto.order_id == "order-1"
    assert dto.amount == 1000


@pytest.mark.parametrize("field", [
    "order_id", "company_id", "company_name", "description",
    "success_url", "cancel_url",
])
def test_empty_string_field_raises(field: str):
    """文字列 field を空にすると InvalidInputError."""
    kwargs = _valid_kwargs()
    kwargs[field] = ""
    with pytest.raises(InvalidInputError):
        CheckoutInput(**kwargs)


@pytest.mark.parametrize("field", [
    "order_id", "company_id", "company_name", "description",
    "success_url", "cancel_url",
])
def test_whitespace_only_field_raises(field: str):
    """文字列 field を whitespace のみにすると InvalidInputError (strip 判定)."""
    kwargs = _valid_kwargs()
    kwargs[field] = "   "
    with pytest.raises(InvalidInputError):
        CheckoutInput(**kwargs)


def test_amount_zero_raises():
    """amount=0 は非正値として弾かれる."""
    kwargs = _valid_kwargs()
    kwargs["amount"] = 0
    with pytest.raises(InvalidInputError):
        CheckoutInput(**kwargs)


def test_amount_negative_raises():
    """amount=負値 は弾かれる."""
    kwargs = _valid_kwargs()
    kwargs["amount"] = -1
    with pytest.raises(InvalidInputError):
        CheckoutInput(**kwargs)


def test_amount_one_ok():
    """amount=1 は境界値で OK."""
    kwargs = _valid_kwargs()
    kwargs["amount"] = 1
    dto = CheckoutInput(**kwargs)
    assert dto.amount == 1
