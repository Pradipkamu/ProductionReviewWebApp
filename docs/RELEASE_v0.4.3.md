# v0.4.3 — Revert OCR capture; defer further OEE work

Restores the v0.4.1 application workflow by removing Shop Production Capture navigation, routes, parsing and OCR execution. Tesseract and Pillow are no longer application dependencies. No replacement manual-entry feature is introduced. Existing Machine / OEE, combined Excel daily upload, process flow and other established features remain as before.

## Install in the existing folder

This update supports v0.4.1 and v0.4.2 installations. Extract the update contents into `D:\Machine Shop MIS`, replacing application files. Preserve `.env` and the entire `database` folder. Start Docker Desktop and run `update_in_place_windows.bat`. If the database is stopped, first run `docker compose up -d db` from that folder. Refresh the browser after a successful update.

The updater creates a verified PostgreSQL backup before starting the changed application. Do not use `docker compose down -v` or restore an older database dump merely to remove the feature.

Migration `0005_shop_capture` and its inert model remain so an installation already upgraded to v0.4.2 can start normally. The capture table, saved images, drafts, review history and any machine records previously imported are preserved. This update does not undo business transactions. An installation still on v0.4.1 may acquire an empty capture table as part of the retained migration chain; no existing facts are altered.

Retired source files contain inert placeholders so extracting this package also disables the old modules without requiring file deletion. The old v0.4.2 release note is historical documentation, not the current feature set.

OCR, automatic shop recognition, new manual shop-entry design and further OEE expansion are deferred until requested again.
