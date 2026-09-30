Production / Process / Sales / Action WebApp v0.2.14
Multi-select filter update

What changed
- Plant, Customer, Type / Product Group and Part scope filters now support multiple selections.
- Quality / Rejection filters now support multiple Plants, Products, Phenomena, Processes, Machines and Shifts.
- Action Status filter supports multiple statuses.
- Management Vendor and Machine report filters support multiple selections.
- Multi-select menus include All, Done and search for long filter lists.
- Backend APIs accept comma-separated multi-select filter values and use SQL IN filtering.

Important
- Operational/data-entry selectors remain single-select where one exact record is required (for example OEE machine entry, Process Monitor selected part, Schedule selected part, action creation Product/Operation/Machine). These are not report filters and making them multi-select would make a transaction ambiguous.
- No database schema change. Existing data is untouched.
- Install over v0.2.13 using Update-in-Place.

Validation
- Backend regression suite: 21 passed, 1 skipped.
- Frontend TypeScript/TSX syntax transpile validation passed.
