import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from billing.models import Business, Invoice
from payments.models import Payment


def _month_bounds(value):
    """Parse 'YYYY-MM' (default: this month) into (first_day, first_day_of_next_month)."""
    today = timezone.localdate()
    try:
        year, month = (int(x) for x in value.split("-"))
        start = datetime.date(year, month, 1)
    except (ValueError, AttributeError):
        start = today.replace(day=1)
    end = (start + datetime.timedelta(days=32)).replace(day=1)
    return start, end


@login_required
def index(request):
    business_code = request.GET.get("business", "")
    start, end = _month_bounds(request.GET.get("month", ""))
    prev_start, _ = _month_bounds((start - datetime.timedelta(days=1)).strftime("%Y-%m"))

    businesses = list(Business.objects.all())
    invoices = Invoice.objects.select_related("client", "business").prefetch_related("items")
    payments = Payment.objects.select_related("invoice__client", "invoice__business")
    if business_code:
        invoices = invoices.filter(business__code=business_code)
        payments = payments.filter(invoice__business__code=business_code)

    confirmed = payments.filter(status=Payment.Status.CONFIRMED)

    def collected(qs, a, b):
        # Revenue to the business excludes the card surcharge passed on to Square.
        agg = qs.filter(confirmed_at__date__gte=a, confirmed_at__date__lt=b).aggregate(
            amount=Sum("amount"), fee=Sum("fee"))
        return (agg["amount"] or Decimal("0")) - (agg["fee"] or Decimal("0"))

    collected_now = collected(confirmed, start, end)
    collected_prev = collected(confirmed, prev_start, start)
    change = None
    if collected_prev:
        change = round((collected_now - collected_prev) / collected_prev * 100)

    open_invoices = invoices.filter(status=Invoice.Status.SENT)
    overdue_invoices = open_invoices.filter(due_date__lt=timezone.localdate())
    month_invoices = invoices.filter(issue_date__gte=start, issue_date__lt=end).exclude(status=Invoice.Status.DRAFT)

    by_business = []
    all_confirmed = Payment.objects.filter(status=Payment.Status.CONFIRMED)
    total_all = collected(all_confirmed, start, end) or Decimal("0")
    for b in businesses:
        amount = collected(all_confirmed.filter(invoice__business=b), start, end)
        by_business.append({
            "business": b,
            "amount": amount,
            "pct": int(amount / total_all * 100) if total_all else 0,
        })

    months = []
    cursor = timezone.localdate().replace(day=1)
    for _ in range(6):
        months.append(cursor)
        cursor = (cursor - datetime.timedelta(days=1)).replace(day=1)

    return render(request, "dashboard/index.html", {
        "business_code": business_code,
        "businesses": businesses,
        "month": start,
        "months": months,
        "collected": collected_now,
        "change": change,
        "outstanding": sum((i.subtotal for i in open_invoices), Decimal("0")),
        "open_count": open_invoices.count(),
        "overdue_count": overdue_invoices.count(),
        "overdue_total": sum((i.subtotal for i in overdue_invoices), Decimal("0")),
        "sent_count": month_invoices.count(),
        "sent_breakdown": [{"business": b, "count": month_invoices.filter(business=b).count()} for b in businesses],
        "pending": payments.filter(status=Payment.Status.PENDING).exclude(method=Payment.Method.CARD),
        "recent": invoices[:8],
        "by_business": by_business,
    })
