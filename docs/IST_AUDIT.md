# Application timestamp audit — 11 October 2026

Base: a7d4cf9 (PR #9). Follow-up repairs the incomplete IST implementation.

- Presentation: Asia/Kolkata (UTC+05:30), with IST labels for actual timestamps.
- Persistence: existing naive UTC database timestamps remain unchanged. No migration.
- Inputs: browser date/time inputs explicitly represent IST; offset-bearing API inputs normalize to naive UTC before database persistence. Legacy naive API inputs retain UTC semantics.
- Calendar dates: production, schedule, effective, reference and review dates remain date-only. Defaults and business-day comparisons use India time.
- Corrected remaining dashboard/MOM deadline displays, administrator deadline editing, governance expiry messages and MOM PDF/Excel targets.
- Corrected backend due-day, closure-day, escalation, ageing and daily report boundaries to use India dates.
- Corrected remaining browser-local/UTC date defaults in dashboard, MIS, process, quality and action pages.
- Preserved UTC security expiry comparisons, event ordering and duration calculations.
- Repaired pre-existing Python import syntax and frontend CSV string syntax errors introduced in PR #9.

Validation: production frontend build, Python compilation, host-timezone-independent frontend tests, and backend boundary/input tests. Baseline backend comparison applies only the Python import syntax repair so the original suite can run. Both baseline and updated suites have existing failures; see PR for counts. No live deployment or browser visual verification was performed.

Existing historical deadlines are not shifted in bulk: earlier clients may have supplied ambiguous naive values. Such records require individual confirmation before correction.
