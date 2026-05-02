"""create_checkout_url + get_payment_status のテスト.

設計のキー:
    - create_checkout_url は Payment を作らない (StripeCustomer のみ)
    - DuplicateOrderError は raise しない
    - idempotency_key は f"checkout-{order_id}-{amount}"
    - metadata={"order_id": ...} を Stripe Session に渡す
    - get_payment_status は 3 値 (NOT_PAID / PAID / REFUNDED)
"""

from unittest.mock import Mock

import pytest
from django.db import IntegrityError

from payment.models import Payment, StripeCustomer
from payment.services.checkout import (
    PaymentStatus,
    create_checkout_url,
    get_payment_status,
)
from payment.services.dtos import CheckoutInput
from payment.stripe import (
    CreateCheckoutSessionOutput,
    PaymentConfigError,
    PaymentSystemError,
)
from payment.tests.factories import PaymentFactory, StripeCustomerFactory


def _make_input(order_id: str = "order-1", company_id: str = "company-1", amount: int = 1000) -> CheckoutInput:
    return CheckoutInput(
        order_id=order_id,
        company_id=company_id,
        company_name="Acme",
        amount=amount,
        description="Product",
        success_url=f"https://example.com/success?order_id={order_id}",
        cancel_url=f"https://example.com/cancel?order_id={order_id}",
    )


def _set_session_response(
    client_mock: Mock,
    session_id: str = "cs_test_x",
    url: str = "https://stripe.example.com/checkout",
) -> None:
    client_mock.create_checkout_session.return_value = CreateCheckoutSessionOutput(
        session_id=session_id,
        url=url,
    )


# ============================================================================
# create_checkout_url
# ============================================================================

@pytest.mark.django_db
def test_returns_url_no_payment_created(mock_stripe_client: Mock):
    """起票時は Payment を作らない. StripeCustomer は作る."""
    mock_stripe_client.create_customer.return_value = "cus_new"
    _set_session_response(
        mock_stripe_client,
        session_id="cs_new",
        url="https://stripe.example.com/abc",
    )

    url = create_checkout_url(_make_input())

    assert url == "https://stripe.example.com/abc"

    # StripeCustomer は作られる
    assert StripeCustomer.objects.filter(company_id="company-1").exists()

    # ★ Payment は作られない (起票時は DB に書かない設計)
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_existing_customer_reused(mock_stripe_client: Mock):
    """既存 StripeCustomer 流用 → create_customer 呼ばれない."""
    StripeCustomerFactory(company_id="company-1", stripe_customer_id="cus_existing")
    _set_session_response(mock_stripe_client)

    create_checkout_url(_make_input())

    mock_stripe_client.create_customer.assert_not_called()
    call_input = mock_stripe_client.create_checkout_session.call_args.args[0]
    assert call_input.customer_id == "cus_existing"


@pytest.mark.django_db
def test_idempotency_key_includes_amount(mock_stripe_client: Mock):
    """idempotency_key に amount が含まれる (amount 変更時に新 Session 作成のため)."""
    mock_stripe_client.create_customer.return_value = "cus_x"
    _set_session_response(mock_stripe_client)

    create_checkout_url(_make_input(order_id="ord-42", amount=5000))

    session_call = mock_stripe_client.create_checkout_session.call_args.args[0]
    assert session_call.idempotency_key == "checkout-ord-42-5000"


@pytest.mark.django_db
def test_metadata_includes_order_id(mock_stripe_client: Mock):
    """metadata に order_id が含まれる (webhook での逆引き用)."""
    mock_stripe_client.create_customer.return_value = "cus_x"
    _set_session_response(mock_stripe_client)

    create_checkout_url(_make_input(order_id="ord-42"))

    session_call = mock_stripe_client.create_checkout_session.call_args.args[0]
    assert session_call.metadata == {"order_id": "ord-42"}


@pytest.mark.django_db
def test_customer_idempotency_key(mock_stripe_client: Mock):
    """create_customer の idempotency_key 検証."""
    mock_stripe_client.create_customer.return_value = "cus_x"
    _set_session_response(mock_stripe_client)

    create_checkout_url(_make_input(company_id="cmp-7"))

    customer_call = mock_stripe_client.create_customer.call_args.args[0]
    assert customer_call.idempotency_key == "customer-cmp-7"


@pytest.mark.django_db
def test_no_duplicate_check(mock_stripe_client: Mock):
    """同 order_id で既に Payment があっても起票は通る (Stripe 側 idempotency に任せる)."""
    PaymentFactory(order_id="order-existing")
    mock_stripe_client.create_customer.return_value = "cus_x"
    _set_session_response(mock_stripe_client)

    # DuplicateOrderError は raise されない
    url = create_checkout_url(_make_input(order_id="order-existing"))

    assert url == "https://stripe.example.com/checkout"


# ============================================================================
# create_checkout_url - StripeCustomer race
# ============================================================================

@pytest.mark.django_db
def test_stripecustomer_race_falls_back_to_existing(
    mock_stripe_client: Mock, monkeypatch: pytest.MonkeyPatch,
):
    """StripeCustomer 作成時の IntegrityError race → 既存を get で取得して続行."""
    StripeCustomerFactory(company_id="company-1", stripe_customer_id="cus_winner")

    mock_stripe_client.create_customer.return_value = "cus_loser"
    _set_session_response(mock_stripe_client)

    # filter(company_id="company-1") を None 返すように偽装 (race 前の状態を再現).
    real_filter = StripeCustomer.objects.filter

    def fake_filter(*args: object, **kwargs: object) -> object:
        if kwargs.get("company_id") == "company-1":
            mock_qs = Mock()
            mock_qs.first.return_value = None
            return mock_qs
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(StripeCustomer.objects, "filter", fake_filter)
    monkeypatch.setattr(
        StripeCustomer.objects, "create",
        Mock(side_effect=IntegrityError("simulated race on company_id unique")),
    )

    create_checkout_url(_make_input())

    session_call = mock_stripe_client.create_checkout_session.call_args.args[0]
    assert session_call.customer_id == "cus_winner"
    assert StripeCustomer.objects.count() == 1


# ============================================================================
# create_checkout_url - 例外伝播
# ============================================================================

@pytest.mark.django_db
def test_payment_system_error_from_create_customer_propagates(mock_stripe_client: Mock):
    mock_stripe_client.create_customer.side_effect = PaymentSystemError("transient")

    with pytest.raises(PaymentSystemError):
        create_checkout_url(_make_input())

    mock_stripe_client.create_checkout_session.assert_not_called()


@pytest.mark.django_db
def test_payment_config_error_from_create_customer_propagates(mock_stripe_client: Mock):
    mock_stripe_client.create_customer.side_effect = PaymentConfigError("permanent")

    with pytest.raises(PaymentConfigError):
        create_checkout_url(_make_input())


@pytest.mark.django_db
def test_payment_system_error_from_create_session_propagates(mock_stripe_client: Mock):
    StripeCustomerFactory(company_id="company-1", stripe_customer_id="cus_x")
    mock_stripe_client.create_checkout_session.side_effect = PaymentSystemError("transient")

    with pytest.raises(PaymentSystemError):
        create_checkout_url(_make_input())


# ============================================================================
# get_payment_status (3 値: NOT_PAID / PAID / REFUNDED)
# ============================================================================

@pytest.mark.django_db
def test_status_not_paid_when_no_payment():
    """Payment 不在 → NOT_PAID (未決済 / キャンセル / 期限切れ全て含む)."""
    assert get_payment_status("missing") == PaymentStatus.NOT_PAID


@pytest.mark.django_db
def test_status_paid_when_payment_exists():
    """Payment 存在 + is_refunded=False → PAID."""
    PaymentFactory(order_id="o", is_refunded=False)
    assert get_payment_status("o") == PaymentStatus.PAID


@pytest.mark.django_db
def test_status_refunded_when_is_refunded_true():
    """Payment 存在 + is_refunded=True → REFUNDED."""
    PaymentFactory(order_id="o", is_refunded=True)
    assert get_payment_status("o") == PaymentStatus.REFUNDED
