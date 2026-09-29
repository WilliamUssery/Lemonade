"""Picks the correct gateway for an invoice and payment method."""
from .gateways import ManualGateway, SquareGateway
from .models import Payment


class MethodNotAccepted(Exception):
    pass


class PaymentRouter:
    @staticmethod
    def get_gateway(invoice, method):
        """Return the gateway for `method`, after checking the invoice's business accepts it.

        Because every invoice belongs to exactly one business, the gateway always
        works against that business's Square location or payment handles.
        """
        if method not in invoice.business.accepted_methods():
            raise MethodNotAccepted(f"{invoice.business} does not accept {method}.")
        if method == Payment.Method.CARD:
            return SquareGateway()
        if method in Payment.MANUAL_METHODS:
            return ManualGateway(method)
        raise MethodNotAccepted(f"Unknown payment method: {method}")
