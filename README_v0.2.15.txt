Production / Process / Sales / Action WebApp v0.2.15
NPM Registry Build Hotfix + v0.2.14 Multi-Select Filters

Purpose
-------
Fixes frontend Docker build failure caused by npm resolving the transitive
package electron-to-chromium to an unavailable tarball version (1.5.443).

Changes
-------
1. Keeps all v0.2.14 Multi-Select Filter changes.
2. Pins the transitive dependency electron-to-chromium to known published
   version 1.5.439 using npm overrides.
3. Frontend Dockerfile explicitly uses the official npm registry and disables
   audit/fund network calls during image build.
4. No database schema or data changes.

Install
-------
1. Optional but recommended: run backup_database_windows.bat
2. Run: docker compose down
3. Extract this ZIP over the current application folder and replace files.
4. Run: docker builder prune -f
5. Run: start_windows.bat
6. After the app opens, press Ctrl+F5 once.

Do NOT run docker compose down -v.
