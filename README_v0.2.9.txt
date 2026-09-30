Production Review Web App v0.2.9 — Chart Rendering + 8 Week Compliance Fix

Changes
-------
1. Compliance weekly graph changed from rolling 12 weeks to rolling 8 weeks.
2. Weekly x-axis labels shortened to Wxx to prevent overlap; exact start/end dates remain in API data and tooltips/context.
3. All SVG report/trend charts now use explicit pixel width/height plus horizontal scrolling when needed.
   This fixes browsers/layouts where responsive SVG charts could render blank/collapsed.
4. Data labels remain ON by default for chart points/bars.
5. Operation weekly compliance is also limited to the latest 8 weeks for consistency.

Install over an existing v0.2.8 installation
------------------------------------------
1. Run backup_database_windows.bat.
2. Run: docker compose down
3. Extract this Update-in-Place ZIP into the application folder and replace files.
4. Run start_windows.bat. It uses docker compose up --build -d, so frontend/backend are rebuilt.
5. If the browser still shows an old page, press Ctrl+F5 once.

Database
--------
No database schema changes are included in v0.2.9. The database folder is not included in this update package.
