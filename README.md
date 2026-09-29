# DualLedger — Unified Client & Payment Portal

Django app for Christie Flowers' two businesses (cleaning and tutoring): one shared client
database, one pay link per invoice, and payments routed to the correct business account.

**Author:** William "Tripp" Ussery · ITEC 2300 Midterm (Option 1)

## Run it

```bash
python -m venv venv
# Windows: venv\Scripts\activate      macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # demo data + login christie / dualledger123
python manage.py runserver
```

Open http://127.0.0.1:8000 and log in. Admin: http://127.0.0.1:8000/admin/

Run the tests: `python manage.py test`

## Apps

| App | Responsibility |
|---|---|
| `clients` | Client model, client↔business links, search, profile page |
| `billing` | Business, Service, Invoice, InvoiceItem; `InvoiceService` (numbering, totals, status); `Notifier` (emails) |
| `payments` | Payment model, `PaymentRouter`, `SquareGateway`, `ManualGateway`, Square webhook |
| `portal` | Public, login-free pay page at `/pay/<uuid>/` |
| `dashboard` | Monthly totals by business, recent invoices, manual-payment confirmation queue; `seed_demo` command |

## How payments work

- **Card:** `SquareGateway` creates a hosted checkout link on the invoice's business Square location,
  so money settles straight to that business. A 3.5% surcharge is added. Square's webhook marks it paid.
- **Zelle / Venmo / Chime:** the pay page shows that business's handle; the client taps "I've sent it",
  and the payment waits as *Pending* until Christie confirms it on the dashboard.
- DualLedger never stores card numbers and never holds money.

## Square Sandbox (optional)

Without keys, card checkout uses a built-in test page. To use the real Square Sandbox,
copy `.env.example` to `.env`, fill in `SQUARE_ACCESS_TOKEN` and `SQUARE_WEBHOOK_SIGNATURE_KEY`,
and set each business's Square location ID in Admin → Businesses.

## Emails

In development, invoice and receipt emails print in the terminal running `runserver`.
