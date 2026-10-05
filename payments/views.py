import csv
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from billing.models import Business

from .gateways import PaymentGateway, SquareGateway
from .models import Payment

log = logging.getLogger(__name__)


def _back(request, default="dashboard:index"):
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(default)


def _filter_payments(request):
    payments = Payment.objects.select_related("invoice__client", "invoice__business", "confirmed_by")
    status = request.GET.get("status", "")
    business_code = request.GET.get("business", "")
    if status:
        payments = payments.filter(status=status)
    if business_code:
        payments = payments.filter(invoice__business__code=business_code)
    return payments, status, business_code


@login_required
def payment_list(request):
    payments, status, business_code = _filter_payments(request)
    return render(request, "payments/list.html", {
        "payments": payments,
        "status": status,
        "business_code": business_code,
        "statuses": Payment.Status.choices,
        "businesses": Business.objects.all(),
    })


@login_required
@require_POST
def payment_confirm(request, pk):
    payment = get_object_or_404(Payment, pk=pk, status=Payment.Status.PENDING)
    PaymentGateway.confirm(payment, user=request.user, external_ref=request.POST.get("reference") or None)
    messages.success(request, f"Confirmed ${payment.amount} {payment.get_method_display()} for "
                              f"{payment.invoice.number}. Receipt emailed.")
    return _back(request)


@login_required
@require_POST
def payment_reject(request, pk):
    payment = get_object_or_404(Payment, pk=pk, status=Payment.Status.PENDING)
    PaymentGateway.reject(payment)
    messages.info(request, f"Rejected {payment.get_method_display()} payment for {payment.invoice.number}.")
    return _back(request)


@csrf_exempt
@require_POST
def square_webhook(request):
    """Square calls this when a card payment completes."""
    signature = request.headers.get("x-square-hmacsha256-signature", "")
    if not SquareGateway.verify_signature(request.body, signature):
        log.warning("Rejected Square webhook with bad signature")
        return HttpResponseForbidden("invalid signature")
    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")
    SquareGateway().handle_event(event)
    return HttpResponse("ok")


def simulate_checkout(request, pk):
    """Development-only stand-in for Square's hosted checkout page."""
    if not settings.SQUARE_SIMULATE:
        raise Http404
    payment = get_object_or_404(Payment.objects.select_related("invoice__business"), pk=pk,
                                method=Payment.Method.CARD)
    invoice = payment.invoice
    if request.method == "POST" and payment.status == Payment.Status.PENDING:
        if "approve" in request.POST:
            PaymentGateway.confirm(payment)
        else:
            PaymentGateway.reject(payment)
        return redirect("portal:done", token=invoice.pay_token)
    return render(request, "payments/simulate.html", {"payment": payment, "invoice": invoice})


@login_required
def payment_export(request):
    payments, *_ = _filter_payments(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="dualledger-payments.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Created", "Invoice", "Business", "Client", "Method", "Amount", "Fee",
                     "Status", "Reference", "Confirmed by", "Confirmed at"])
    for p in payments:
        writer.writerow([
            p.created_at.strftime("%Y-%m-%d %H:%M"), p.invoice.number, p.invoice.business.name,
            p.invoice.client.full_name, p.get_method_display(), p.amount, p.fee,
            p.get_status_display(), p.external_ref,
            p.confirmed_by.username if p.confirmed_by else "",
            p.confirmed_at.strftime("%Y-%m-%d %H:%M") if p.confirmed_at else "",
        ])
    return response
