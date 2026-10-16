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


## Machine shop working calendar default

The machine shop does not assume Sunday (or any other weekday) is automatically off.
Every date is treated as a working day unless that date is explicitly marked as non-working in the plant Working Calendar. Use the calendar to select weekly offs, Sundays, Saturdays, shutdowns and public holidays for each plant. Planning calculations and the Daily Review Production Review Date use the same plant calendar.
