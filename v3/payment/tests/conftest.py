"""共通 fixture.

`mock_stripe_client`: get_stripe_client を Mock(spec=StripeClient) に差し替える.
service と view 両方の参照を patch するため、どちらの test でも使える.

`real_mock_client`: Mock ではなく実体の StripeClientMock を inject する.
mock_checkout_view 等 `client._sessions` にアクセスする path のテスト用.
"""

from typing import Any
from unittest.mock import Mock

import pytest

from payment.stripe import StripeClient
from payment.stripe.client_mock import StripeClientMock


@pytest.fixture
def mock_stripe_client(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """get_stripe_client を Mock(spec=StripeClient) に差替.

    service / view のどちらから呼ばれても同じ Mock を返すよう両 module を patch.
    テスト内では `mock_stripe_client.create_customer.return_value = "..."` のように
    各メソッドの戻り値 / side_effect を設定する.
    """
    client: Any = Mock(spec=StripeClient)
    monkeypatch.setattr("payment.services.checkout.get_stripe_client", lambda: client)
    monkeypatch.setattr("payment.views.get_stripe_client", lambda: client)
    return client


@pytest.fixture
def real_mock_client(monkeypatch: pytest.MonkeyPatch) -> StripeClientMock:
    """実体の StripeClientMock を inject. _sessions の状態を直接いじりたいテスト用."""
    client = StripeClientMock()
    monkeypatch.setattr("payment.services.checkout.get_stripe_client", lambda: client)
    monkeypatch.setattr("payment.views.get_stripe_client", lambda: client)
    return client
