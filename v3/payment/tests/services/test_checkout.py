"""create_checkout_url + get_payment_status のテスト."""

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
from payment.services.exceptions import DuplicateOrderError
from payment.stripe import (
    CreateCheckoutSessionOutput,
    PaymentConfigError,
    PaymentSystemError,
)
from payment.tests.factories import PaymentFactory, StripeCustomerFactory


def _make_input(order_id: str = "order-1", company_id: str = "company-1") -> CheckoutInput:
    """テスト用 CheckoutInput. デフォルト値は happy path 想定."""
    return CheckoutInput(
        order_id=order_id,
        company_id=company_id,
        company_name="Acme",
        amount=1000,
        description="Product",
        success_url=f"https://example.com/success?order_id={order_id}",
        cancel_url=f"https://example.com/cancel?order_id={order_id}",
    )


def _set_session_response(
    client_mock: Mock,
    session_id: str = "cs_test_x",
    payment_intent_id: str = "pi_test_x",
    url: str = "https://stripe.example.com/checkout",
) -> None:
    """create_checkout_session の戻り値を仕込む."""
    client_mock.create_checkout_session.return_value = CreateCheckoutSessionOutput(
        session_id=session_id,
        payment_intent_id=payment_intent_id,
        url=url,
    )


# ============================================================================
# create_checkout_url - happy path
# ============================================================================

@pytest.mark.django_db
def test_create_new_customer_and_payment(mock_stripe_client: Mock):
    """StripeCustomer 不在 → Stripe call → DB に StripeCustomer + Payment 作成."""
    mock_stripe_client.create_customer.return_value = "cus_new"
    _set_session_response(
        mock_stripe_client,
        session_id="cs_new",
        payment_intent_id="pi_new",
        url="https://stripe.example.com/abc",
    )

    url = create_checkout_url(_make_input())

    assert url == "https://stripe.example.com/abc"

    customer = StripeCustomer.objects.get(company_id="company-1")
    assert customer.stripe_customer_id == "cus_new"
    assert customer.company_name == "Acme"

    payment = Payment.objects.get(order_id="order-1")
    assert payment.stripe_customer == customer
    assert payment.stripe_session_id == "cs_new"
    assert payment.stripe_payment_id == "pi_new"
    assert payment.amount == 1000
    assert payment.description == "Product"
    assert payment.session_status == Payment.SessionStatus.PENDING
    assert payment.payment_status == Payment.PaymentStatus.UNPAID


@pytest.mark.django_db
def test_create_existing_customer_skips_stripe_create(mock_stripe_client: Mock):
    """既存 StripeCustomer 流用 → create_customer 呼ばれない."""
    StripeCustomerFactory(company_id="company-1", stripe_customer_id="cus_existing")
    _set_session_response(mock_stripe_client)

    create_checkout_url(_make_input())

    mock_stripe_client.create_customer.assert_not_called()
    # session 作成時に existing customer ID が使われた
    call_input = mock_stripe_client.create_checkout_session.call_args.args[0]
    assert call_input.customer_id == "cus_existing"


# ============================================================================
# create_checkout_url - idempotency_key 検証
# ============================================================================

@pytest.mark.django_db
def test_create_uses_idempotency_keys(mock_stripe_client: Mock):
    """create_customer / create_checkout_session の idempotency_key を検証."""
    mock_stripe_client.create_customer.return_value = "cus_x"
    _set_session_response(mock_stripe_client)

    create_checkout_url(_make_input(order_id="ord-42", company_id="cmp-7"))

    customer_call = mock_stripe_client.create_customer.call_args.args[0]
    assert customer_call.idempotency_key == "customer-cmp-7"

    session_call = mock_stripe_client.create_checkout_session.call_args.args[0]
    assert session_call.idempotency_key == "checkout-ord-42"


# ============================================================================
# create_checkout_url - 二重起票
# ============================================================================

@pytest.mark.django_db
def test_create_duplicate_order_pre_check(mock_stripe_client: Mock):
    """同 order_id の Payment 存在 → DuplicateOrderError、Stripe 呼ばれない."""
    PaymentFactory(order_id="order-dup")

    with pytest.raises(DuplicateOrderError) as exc_info:
        create_checkout_url(_make_input(order_id="order-dup"))

    assert exc_info.value.order_id == "order-dup"
    mock_stripe_client.create_customer.assert_not_called()
    mock_stripe_client.create_checkout_session.assert_not_called()


@pytest.mark.django_db
def test_create_payment_race_raises_duplicate(
    mock_stripe_client: Mock, monkeypatch: pytest.MonkeyPatch,
):
    """Payment.objects.create で IntegrityError race → DuplicateOrderError に変換."""
    mock_stripe_client.create_customer.return_value = "cus_x"
    _set_session_response(mock_stripe_client)

    monkeypatch.setattr(
        Payment.objects, "create",
        Mock(side_effect=IntegrityError("simulated race on order_id unique")),
    )

    with pytest.raises(DuplicateOrderError) as exc_info:
        create_checkout_url(_make_input(order_id="order-race"))

    assert exc_info.value.order_id == "order-race"


# ============================================================================
# create_checkout_url - StripeCustomer race
# ============================================================================

@pytest.mark.django_db
def test_stripecustomer_race_falls_back_to_existing(
    mock_stripe_client: Mock, monkeypatch: pytest.MonkeyPatch,
):
    """StripeCustomer 作成時の IntegrityError race → 既存を get で取得して続行.

    シナリオ:
        1. service: StripeCustomer.filter().first() → None (race 前の状態)
        2. service: client.create_customer → "cus_loser" (我々が作ろうとした)
        3. service: StripeCustomer.create() → IntegrityError (別 thread が先勝)
        4. service: StripeCustomer.get() → winner (race 勝者) を返す
    """
    winner = StripeCustomerFactory(
        company_id="company-1", stripe_customer_id="cus_winner",
    )

    mock_stripe_client.create_customer.return_value = "cus_loser"
    _set_session_response(mock_stripe_client)

    # filter(company_id="company-1") を None 返すように偽装 (race 前の状態を再現).
    # 他の filter (Payment 等) には影響しない.
    real_filter = StripeCustomer.objects.filter

    def fake_filter(*args: object, **kwargs: object) -> object:
        if kwargs.get("company_id") == "company-1":
            mock_qs = Mock()
            mock_qs.first.return_value = None
            return mock_qs
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(StripeCustomer.objects, "filter", fake_filter)

    # create で IntegrityError (race の本番)
    monkeypatch.setattr(
        StripeCustomer.objects, "create",
        Mock(side_effect=IntegrityError("simulated race on company_id unique")),
    )

    create_checkout_url(_make_input())

    # winner の customer_id が Stripe Session に渡っている
    session_call = mock_stripe_client.create_checkout_session.call_args.args[0]
    assert session_call.customer_id == "cus_winner"

    # Payment は winner と紐付き
    payment = Payment.objects.get(order_id="order-1")
    assert payment.stripe_customer == winner


# ============================================================================
# create_checkout_url - 例外伝播
# ============================================================================

@pytest.mark.django_db
def test_payment_system_error_from_create_customer_propagates(mock_stripe_client: Mock):
    """create_customer の PaymentSystemError は service が catch せず素通し."""
    mock_stripe_client.create_customer.side_effect = PaymentSystemError("transient")

    with pytest.raises(PaymentSystemError):
        create_checkout_url(_make_input())

    mock_stripe_client.create_checkout_session.assert_not_called()


@pytest.mark.django_db
def test_payment_config_error_from_create_customer_propagates(mock_stripe_client: Mock):
    """create_customer の PaymentConfigError は素通し."""
    mock_stripe_client.create_customer.side_effect = PaymentConfigError("permanent")

    with pytest.raises(PaymentConfigError):
        create_checkout_url(_make_input())


@pytest.mark.django_db
def test_payment_system_error_from_create_session_propagates(mock_stripe_client: Mock):
    """create_checkout_session の PaymentSystemError は素通し."""
    StripeCustomerFactory(company_id="company-1", stripe_customer_id="cus_x")
    mock_stripe_client.create_checkout_session.side_effect = PaymentSystemError("transient")

    with pytest.raises(PaymentSystemError):
        create_checkout_url(_make_input())

    # Payment は作成されない
    assert Payment.objects.count() == 0


# ============================================================================
# get_payment_status
# ============================================================================

@pytest.mark.django_db
def test_status_not_found():
    """Payment 不在 → NOT_FOUND."""
    assert get_payment_status("missing") == PaymentStatus.NOT_FOUND


@pytest.mark.django_db
def test_status_succeeded():
    """payment_status=SUCCEEDED → SUCCEEDED (payment_status 優先)."""
    PaymentFactory(
        order_id="o",
        session_status=Payment.SessionStatus.COMPLETED,
        payment_status=Payment.PaymentStatus.SUCCEEDED,
    )
    assert get_payment_status("o") == PaymentStatus.SUCCEEDED


@pytest.mark.django_db
def test_status_refunded_takes_precedence_over_completed():
    """REFUNDED は SUCCEEDED より優先 (完了後返金が新しい真実)."""
    PaymentFactory(
        order_id="o",
        session_status=Payment.SessionStatus.COMPLETED,
        payment_status=Payment.PaymentStatus.REFUNDED,
    )
    assert get_payment_status("o") == PaymentStatus.REFUNDED


@pytest.mark.django_db
def test_status_canceled():
    """session_status=CANCELED + payment_status=UNPAID → CANCELED."""
    PaymentFactory(
        order_id="o",
        session_status=Payment.SessionStatus.CANCELED,
        payment_status=Payment.PaymentStatus.UNPAID,
    )
    assert get_payment_status("o") == PaymentStatus.CANCELED


@pytest.mark.django_db
def test_status_expired():
    """session_status=EXPIRED + payment_status=UNPAID → EXPIRED."""
    PaymentFactory(
        order_id="o",
        session_status=Payment.SessionStatus.EXPIRED,
        payment_status=Payment.PaymentStatus.UNPAID,
    )
    assert get_payment_status("o") == PaymentStatus.EXPIRED


@pytest.mark.django_db
def test_status_pending_default():
    """session_status=PENDING + payment_status=UNPAID → PENDING (デフォルト)."""
    PaymentFactory(
        order_id="o",
        session_status=Payment.SessionStatus.PENDING,
        payment_status=Payment.PaymentStatus.UNPAID,
    )
    assert get_payment_status("o") == PaymentStatus.PENDING
