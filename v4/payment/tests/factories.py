"""factory_boy factories for payment models."""

from factory import Sequence, SubFactory
from factory.django import DjangoModelFactory

from payment.models import Payment, StripeCustomer, StripeWebhookEventLog


class StripeCustomerFactory(DjangoModelFactory):
    class Meta:
        model = StripeCustomer

    company_id = Sequence(lambda n: f"company-{n}")
    company_name = Sequence(lambda n: f"Company {n}")
    stripe_customer_id = Sequence(lambda n: f"cus_test_{n:020d}")


class PaymentFactory(DjangoModelFactory):
    class Meta:
        model = Payment

    stripe_customer = SubFactory(StripeCustomerFactory)
    order_id = Sequence(lambda n: f"order-{n}")
    stripe_session_id = Sequence(lambda n: f"cs_test_{n:020d}")
    stripe_payment_id = Sequence(lambda n: f"pi_test_{n:020d}")
    amount = 1000
    description = "Test product"


class StripeWebhookEventLogFactory(DjangoModelFactory):
    class Meta:
        model = StripeWebhookEventLog

    event_id = Sequence(lambda n: f"evt_test_{n:020d}")
    event_type = "checkout.session.completed"
