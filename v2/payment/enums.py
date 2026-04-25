"""payment app の公開 enum."""

from enum import StrEnum


class PaymentStatus(StrEnum):
    """payment app が外部に公開する決済状態. session/payment 2カラムを統合した値."""

    NOT_FOUND = "not_found"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
