"""The only public part of DualLedger: the login-free pay page reached by an invoice's pay link."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from billing.models import Invoice
from payments.gateways import GatewayError, ManualGateway
from payments.models import Payment
from payments.router import MethodNotAccepted, PaymentRouter


def _get_invoice(token):
    # 404 for drafts so an unsent invoice can't be seen even with its token.
    return get_object_or_404(
        Invoice.objects.select_related("business", "client").prefetch_related("items", "payments")
        .exclude(status=Invoice.Status.DRAFT),
        pay_token=token,
    )


def pay(request, token):
    invoice = _get_invoice(token)
    selected = request.GET.get("method", "")
    methods = []
    for method in invoice.business.accepted_methods():
        entry = {"value": method, "label": Payment.Method(method).label}
        if method == Payment.Method.CARD:
            entry.update(amount=invoice.card_total, fee=invoice.card_fee)
        else:
            entry.update(ManualGateway(method).instructions(invoice))
        methods.append(entry)
    pending = invoice.payments.filter(status=Payment.Status.PENDING).exclude(method=Payment.Method.CARD).first()
    return render(request, "portal/pay.html", {
        "invoice": invoice,
        "methods": methods,
        "selected": selected,
        "pending": pending,
    })


@require_POST
def start_payment(request, token):
    invoice = _get_invoice(token)
    if not invoice.is_payable:
        return redirect("portal:pay", token=token)
    method = request.POST.get("method", "")
    try:
        gateway = PaymentRouter.get_gateway(invoice, method)
    except MethodNotAccepted:
        messages.error(request, "That payment method isn't available for this invoice.")
        return redirect("portal:pay", token=token)

    if method == Payment.Method.CARD:
        try:
            done_url = request.build_absolute_uri(invoice.get_pay_url() + "done/")
            payment = gateway.start(invoice, redirect_url=done_url)
        except GatewayError:
            messages.error(request, "Card checkout is unavailable right now. Please try another method.")
            return redirect("portal:pay", token=token)
        return redirect(payment.checkout_url)

    gateway.start(invoice, memo=request.POST.get("memo", "").strip()[:120])
    return redirect("portal:done", token=token)


def done(request, token):
    invoice = _get_invoice(token)
    latest = invoice.payments.first()
    return render(request, "portal/done.html", {"invoice": invoice, "payment": latest})
