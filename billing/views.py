import csv
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clients.models import Client

from .forms import InvoiceForm, InvoiceItemFormSet
from .models import Business, Invoice, Service
from .services import InvalidTransition, InvoiceService


def _filter_invoices(request):
    """Shared by the list page and the CSV export so both show the same rows."""
    invoices = Invoice.objects.select_related("client", "business").prefetch_related("items", "payments")
    status = request.GET.get("status", "")
    business_code = request.GET.get("business", "")
    q = request.GET.get("q", "").strip()
    if status == "overdue":
        invoices = invoices.filter(status=Invoice.Status.SENT, due_date__lt=timezone.localdate())
    elif status:
        invoices = invoices.filter(status=status)
    if business_code:
        invoices = invoices.filter(business__code=business_code)
    if q:
        invoices = invoices.filter(
            Q(number__icontains=q) | Q(client__first_name__icontains=q) | Q(client__last_name__icontains=q)
        )
    return invoices, status, business_code, q


@login_required
def invoice_list(request):
    invoices, status, business_code, q = _filter_invoices(request)
    return render(request, "billing/list.html", {
        "invoices": invoices,
        "status": status,
        "business_code": business_code,
        "q": q,
        "statuses": Invoice.Status.choices + [("overdue", "Overdue")],
        "businesses": Business.objects.all(),
    })


def _form_context(form, formset, **extra):
    """Services, payment methods and client links go to the page as JSON so the
    form can filter line items by business and total them live."""
    services = Service.objects.filter(active=True).select_related("business")
    businesses = Business.objects.all()
    catalog = {
        "services": {s.pk: {"business": s.business_id, "rate": str(s.rate), "name": s.name} for s in services},
        "businesses": {
            b.pk: {
                "name": b.name,
                "methods": [
                    label for label, on in [
                        ("Card (Square)", b.accepts_card),
                        (f"Zelle · {b.zelle_handle}", b.zelle_handle),
                        (f"Venmo · {b.venmo_handle}", b.venmo_handle),
                        (f"Chime · {b.chime_handle}", b.chime_handle),
                    ] if on
                ],
            }
            for b in businesses
        },
        "clientLinks": {
            c.pk: [b.pk for b in c.businesses.all()] for c in Client.objects.prefetch_related("businesses")
        },
    }
    return {"form": form, "formset": formset, "catalog": catalog, **extra}


def _business_from_post(request):
    try:
        return Business.objects.get(pk=request.POST.get("business"))
    except (Business.DoesNotExist, ValueError):
        return None


@login_required
def invoice_create(request):
    initial = {}
    if request.GET.get("client"):
        initial["client"] = request.GET["client"]
        client = Client.objects.filter(pk=request.GET["client"]).first()
        if client and client.businesses.count() == 1:
            initial["business"] = client.businesses.first().pk

    if request.method == "POST":
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST, prefix="items", business=_business_from_post(request))
        if form.is_valid() and formset.is_valid():
            invoice = InvoiceService.create_invoice(
                **form.cleaned_data, items=formset.items(), user=request.user
            )
            if "send" in request.POST:
                InvoiceService.send(invoice)
                messages.success(request, f"{invoice.number} sent to {invoice.client.email}.")
            else:
                messages.success(request, f"Draft {invoice.number} saved.")
            return redirect(invoice)
    else:
        form = InvoiceForm(initial=initial)
        formset = InvoiceItemFormSet(prefix="items")
    return render(request, "billing/form.html", _form_context(form, formset, title="New invoice"))


@login_required
def invoice_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if not invoice.is_editable:
        messages.error(request, "Only draft invoices can be edited.")
        return redirect(invoice)

    if request.method == "POST":
        form = InvoiceForm(request.POST)
        form.fields["business"].disabled = True
        form.fields["business"].initial = invoice.business
        formset = InvoiceItemFormSet(request.POST, prefix="items", business=invoice.business)
        if form.is_valid() and formset.is_valid():
            data = form.cleaned_data
            invoice.client = data["client"]
            invoice.issue_date = data["issue_date"]
            invoice.due_date = data["due_date"]
            invoice.message = data["message"]
            invoice.save()
            InvoiceService.set_items(invoice, formset.items())
            if "send" in request.POST:
                InvoiceService.send(invoice)
                messages.success(request, f"{invoice.number} sent to {invoice.client.email}.")
            else:
                messages.success(request, "Draft saved.")
            return redirect(invoice)
    else:
        form = InvoiceForm(initial={
            "client": invoice.client, "business": invoice.business, "issue_date": invoice.issue_date,
            "due_date": invoice.due_date, "message": invoice.message,
        })
        form.fields["business"].disabled = True
        formset = InvoiceItemFormSet(prefix="items", initial=[
            {"service": i.service, "description": i.description, "quantity": i.quantity, "unit_price": i.unit_price}
            for i in invoice.items.all()
        ])
    return render(request, "billing/form.html",
                  _form_context(form, formset, title=f"Edit {invoice.number}", invoice=invoice))


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "business").prefetch_related("items", "payments"), pk=pk
    )
    return render(request, "billing/detail.html", {
        "invoice": invoice,
        "pay_url": request.build_absolute_uri(invoice.get_pay_url()),
    })


@login_required
@require_POST
def invoice_send(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    try:
        InvoiceService.send(invoice)
        messages.success(request, f"{invoice.number} sent to {invoice.client.email}.")
    except InvalidTransition as exc:
        messages.error(request, str(exc))
    return redirect(invoice)


@login_required
@require_POST
def invoice_void(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    try:
        InvoiceService.void(invoice)
        messages.success(request, f"{invoice.number} voided.")
    except InvalidTransition as exc:
        messages.error(request, str(exc))
    return redirect(invoice)


@login_required
@require_POST
def invoice_resend(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    try:
        InvoiceService.resend(invoice)
        messages.success(request, f"{invoice.number} resent to {invoice.client.email}.")
    except InvalidTransition as exc:
        messages.error(request, str(exc))
    return redirect(invoice)


@login_required
@require_POST
def invoice_remind(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    try:
        InvoiceService.remind(invoice)
        messages.success(request, f"Reminder for {invoice.number} sent to {invoice.client.email}.")
    except InvalidTransition as exc:
        messages.error(request, str(exc))
    return redirect(invoice)


@login_required
def invoice_export(request):
    invoices, *_ = _filter_invoices(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="dualledger-invoices.csv"'
    response.write("\ufeff")  # BOM so Excel reads names with accents correctly
    writer = csv.writer(response)
    writer.writerow(["Invoice", "Business", "Client", "Email", "Issued", "Due", "Status",
                     "Subtotal", "Card fee charged", "Amount paid"])
    for inv in invoices:
        confirmed = [p for p in inv.payments.all() if p.status == "confirmed"]
        writer.writerow([
            inv.number, inv.business.name, inv.client.full_name, inv.client.email,
            inv.issue_date, inv.due_date, inv.status_label, inv.subtotal,
            sum((p.fee for p in confirmed), Decimal("0")),
            sum((p.amount for p in confirmed), Decimal("0")),
        ])
    return response
