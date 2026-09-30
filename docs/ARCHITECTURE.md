# Architecture

```text
Browser / Mobile / Tablet
          |
      React UI
          |
      FastAPI API
          |
  -----------------------------
  | Planning | Process | Action |
  | Vendor   | OEE     | MIS    |
  -----------------------------
          |
      PostgreSQL
          |
 Power BI / Excel / future AFMS
```

## Core flow

```text
Customer Schedule
      ↓
Schedule Revision Engine
      ↓
Dispatch Daily Requirement
      ↓
Route / Yield / Lead-Time Engine
      ↓
Operation Daily Requirement
      ↓
Actual Production / Vendor Movement / Machine OEE
      ↓
WIP + Exceptions
      ↓
Date-wise Operation Action
      ↓
Follow-up → Closure → Effectiveness
      ↓
Historical Analytics / Power BI
```

## Design principles

1. Never destroy historical values; version schedules, routes, prices and actions.
2. Excel coordinates exist only in the import adapter. The application uses IDs.
3. Actions are contextual: date + product + operation + optional machine/loss.
4. Machine data is optional initially and compatible with future AFMS/MQTT ingestion.
5. Process routes are variable-length; no fixed Operation1/Operation2 columns.
6. Vendor operations are first-class route steps with WIP and aging.
