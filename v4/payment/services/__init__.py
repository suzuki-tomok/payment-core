"""payment app の service 層.

caller (view 等) はここの submodule から直接 import する:
    from payment.services.checkout import create_checkout_url
    from payment.services.dtos import CheckoutInput
    from payment.services.exceptions import InvalidInputError
"""
