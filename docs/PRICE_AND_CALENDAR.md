# Price Revision & Working Calendar — v0.2.2

## Sales price revision
Open **Schedule / Price / Calendar**. Select the Product, enter Effective From, New Price and Reason, then apply the revision.

The price history is effective-dated. Earlier dates retain their historical price. Existing Daily MIS rows from the effective date forward are recalculated. Future Excel re-imports use the effective price history and cannot silently replace a manual revision.

## Working calendar
The calendar is Plant-specific. If no explicit row exists, the default is Monday-Saturday working and Sunday off.

The calendar screen supports:
- individual date toggle with Holiday/Off-day name and Reason,
- Set Sundays Off for a range,
- Mark Range Off,
- Mark Range Working,
- change history / audit trail.

After a calendar change, use **Recalculate month** when revised schedule requirements should be redistributed using the changed working days.
