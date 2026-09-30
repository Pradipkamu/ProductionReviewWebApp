# Database map

## Masters
- `users`
- `customers`
- `products`
- `vendors`
- `operations`
- `machines`
- `loss_categories`
- `working_calendar`
- `sales_price_history`

## Route / machine planning
- `route_versions`
- `route_operations`
- `operation_machine_map`
- `standard_cycle_times`

## Planning
- `schedule_revisions`
- `daily_requirements`

## MIS / production
- `daily_mis`
- `mis_change_log`
- `process_daily_summary`
- `vendor_movements`
- `machine_shift_production`
- `machine_loss_events`

## Actions / review
- `actions`
- `action_contexts`
- `action_history`
- `review_sessions`
- `review_action_links`
- `month_status`

## Versioning rules
- Schedule revisions are append-only.
- Route revisions are append-only.
- Sales prices have effective dates.
- Historical MIS edits create `mis_change_log` records.
- Action status changes create `action_history` records.

## v0.1.4 product reporting dimensions

`products` additionally carries:

- `plant` — optional plant/site/unit reporting dimension
- `product_group` — optional product/category/business-group reporting dimension
- `finish_weight_kg` — finished part weight used to convert Qty to metric tonnes

These fields are master attributes and therefore filter the same product consistently across MIS, schedules, process monitoring, actions and reports. The web app adds missing nullable columns to an existing v0.1.x database at startup; a full Alembic migration chain remains recommended before enterprise rollout.

## v0.2.0 persistence / import audit
- `import_batches` — SHA-256 hash, original filename, import user/time and import statistics.
- `products.product_group` stores the Excel `Type` field as the Type / Product Group reporting dimension.
- `products.plant` stores the Excel `Plant` field as text, including numeric plant codes such as `2020`.

All live PostgreSQL files are bind-mounted under `database/postgres/`; imported files and backups are also kept under `database/` so application source can be upgraded independently.
