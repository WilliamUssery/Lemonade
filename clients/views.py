from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from billing.models import Business, Invoice, InvoiceItem

from .forms import ClientForm
from .models import Client


@login_required
def client_list(request):
    q = request.GET.get("q", "").strip()
    business_code = request.GET.get("business", "")
    clients = Client.objects.prefetch_related("businesses").annotate(invoice_count=Count("invoices"))
    if q:
        clients = clients.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
        )
    if business_code:
        clients = clients.filter(businesses__code=business_code)
    return render(request, "clients/list.html", {
        "clients": clients,
        "q": q,
        "business_code": business_code,
        "businesses": Business.objects.all(),
    })


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client.objects.prefetch_related("businesses"), pk=pk)
    business_code = request.GET.get("business", "")
    invoices = client.invoices.select_related("business").prefetch_related("items", "payments")
    if business_code:
        invoices = invoices.filter(business__code=business_code)

    billed_items = InvoiceItem.objects.filter(invoice__client=client).exclude(invoice__status=Invoice.Status.VOID)
    open_items = billed_items.filter(invoice__status=Invoice.Status.SENT)

    def total(qs):
        return sum((item.amount for item in qs), 0)

    confirmed = client.invoices.filter(payments__status="confirmed").values("payments__method")
    preferred = (
        confirmed.annotate(n=Count("id")).order_by("-n").first() if confirmed.exists() else None
    )
    method_labels = {"card": "Card", "zelle": "Zelle", "venmo": "Venmo", "chime": "Chime"}

    return render(request, "clients/detail.html", {
        "client": client,
        "invoices": invoices,
        "business_code": business_code,
        "businesses": client.businesses.all(),
        "lifetime_billed": total(billed_items),
        "open_balance": total(open_items),
        "preferred_method": method_labels.get(preferred["payments__method"]) if preferred else "—",
    })


@login_required
def client_create(request):
    form = ClientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        client = form.save()
        messages.success(request, f"Added {client.full_name}.")
        return redirect(client)
    return render(request, "clients/form.html", {"form": form, "title": "New client"})


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Client updated.")
        return redirect(client)
    return render(request, "clients/form.html", {"form": form, "title": f"Edit {client.full_name}", "client": client})
