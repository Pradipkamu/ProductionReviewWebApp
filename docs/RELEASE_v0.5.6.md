# v0.5.6 — Casting Quality, Customer Quality and Value Addition

## Safe upgrade

Use the normal in-place updater. Migration `0012_casting_customer_quality` is additive: it adds new quality tables, import-batch tables, product value-addition history and one nullable Product column. Existing production, rejection, product and security data are preserved.

Keep the current Oracle deployment settings until working HTTPS is available:

```env
REQUIRE_HTTPS=false
DB_BIND=127.0.0.1
BACKEND_BIND=127.0.0.1
```

Do not use `docker compose down -v`.

## Casting Quality

- Separate casting-defect phenomenon master.
- Manual entry for date, shift, product, foundry/vendor, heat/batch, inspected quantity, defect, rework, scrap and remark.
- Casting PPM = Defect Qty ÷ Inspected Qty × 1,000,000.
- Validation prevents negative quantities, defects above inspected quantity, and rework plus scrap above total defects.
- Daily weighted PPM trend, phenomenon Pareto, product Pareto and record detail.
- Protected master-driven Excel template and atomic Preview/Confirm import.

## Customer Quality

- Separate customer-rejection phenomenon master.
- Manual entry for customer, product, complaint/reference, batch, dispatch/received quantity, rejected quantity and remark.
- Customer PPM = Reject Qty ÷ Dispatch/Received Qty × 1,000,000.
- Product/customer assignment and quantity consistency validation.
- Daily weighted PPM trend, phenomenon Pareto, customer Pareto and record detail.
- Protected master-driven Excel template and atomic Preview/Confirm import.

Internal machining, casting and customer PPM remain separate. This prevents unlike denominators from being added together.

## Product Value Addition

Product Master shows the current value addition in ₹/piece. A change is saved as an append-only revision with effective date, reason and user. Backdated changes remain subject to month-close/correction governance. Future-dated revisions are rejected so the Product snapshot cannot silently become stale; create the revision when it becomes effective.

## Access

Authenticated users can read the new reports. Quality and Admin can add phenomena, records and imports. Quality and Admin can create value-addition revisions; existing broader Product/Master permissions are unchanged. Admin controls whether the Casting Quality and Customer Quality pages appear for each role in **Security / Users → Page Visibility by Role**. Page visibility does not override backend authorization.
