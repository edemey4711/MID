# Copilot / AI agent instructions for MTBUploadPicToMap

Short, practical notes to get productive quickly.

## Project overview
- Small Flask web app for uploading and displaying geotagged photos.
- Key files: `app.py` (single-module app), `requirements.txt`, `templates/` (Jinja templates), `static/` (icons, `uploads/` for uploaded images), `database.db` (SQLite, created at runtime).
- Routes to know: `/upload`, `/map`, `/gallery`, `/detail/<id>`, `/edit/<id>`, `/delete/<id>`.

## Quick run / debug steps (Windows)
1. Activate venv: `venv\Scripts\Activate.ps1` (PowerShell) or `venv\Scripts\activate` (cmd).
2. Install dependencies: `pip install -r requirements.txt`.
   - Note: The project uses `pillow_heif` but it is NOT listed in `requirements.txt`—install it manually: `pip install pillow-heif`.
3. Start dev server: `python app.py` (the app includes `app.run(debug=True)` so this is sufficient).
4. DB: the SQLite DB `database.db` is created automatically by `init_db()` in `app.py`.

## Important patterns & conventions
- Single-file Flask app: most logic lives in `app.py`. Small changes often affect many behaviors (DB schema, uploads, templates).
- Categories: `ALLOWED_CATEGORIES` (in `app.py`) is the authoritative list. When adding a category, update:
  - `ALLOWED_CATEGORIES` in `app.py`
  - options in `templates/upload.html`, `templates/edit.html`, `templates/map.html` (filter select and icons)
  - icons in `static/icons/`
- File storage: uploaded files are written to `static/uploads/`. Template paths assume `img[4]` holds a path like `static/uploads/xxx.jpg` (templates either prefix with `/` or use directly).
- EXIF/HEIF handling: HEIF/HEIC images are converted to JPEG via `pillow_heif` and EXIF is read from the saved JPEG when possible. EXIF parsing is done with Pillow helpers in `get_exif_data()` and `get_lat_lon()`.

## Database notes & gotchas (must-read)
- `init_db()` (run at import) now ensures a canonical `images` schema and will add missing columns on older databases (uses `ALTER TABLE ... ADD COLUMN` where necessary).
- The canonical columns are: `id, name, description, category, filepath, latitude, longitude, upload_date, upload_time, exif_date, exif_time, uploaded_at`.
  - This keeps the INSERT/SELECT statements in the app consistent with the schema. If you have an existing `database.db` from an older run, `init_db()` will attempt to migrate it in place; if migration isn't possible, delete `database.db` to recreate it.
  - Example canonical CREATE:
    CREATE TABLE images (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      description TEXT,
      category TEXT,
      filepath TEXT NOT NULL,
      latitude REAL,
      longitude REAL,
      upload_date TEXT,
      upload_time TEXT,
      exif_date TEXT,
      exif_time TEXT,
      uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
- Templates rely on tuple index ordering from SQL `SELECT`s. Common mapping used in templates:
  - img[0]=id, img[1]=name, img[2]=description, img[3]=category, img[4]=filepath, img[5]=latitude, img[6]=longitude, img[7]=upload_date, img[8]=upload_time, img[9]=exif_date, img[10]=exif_time
  - Be cautious: `map` and `gallery` often SELECT a subset of columns — check queries when changing templates.

## Common tasks & tips for contributors / agents
- Adding a new category: update `ALLOWED_CATEGORIES` + template selects + `static/icons/<your-icon>.svg` + `map.js` icon map in `templates/map.html`.
- Fixing DB schema issues: update `init_db()` and then either delete `database.db` to re-create or write a migration script (no migration tooling present).
- Reproducing upload bugs: upload a test JPG and a HEIC file. Check `static/uploads/` and `database.db`. Use `sqlite3 database.db` to inspect rows.
- Silent exceptions: EXIF parsing and file deletion use broad try/except in several places — when debugging, add more specific logging or temporarily raise exceptions to see stack traces.

## Dependencies & environment
- Declared: `Flask`, `Werkzeug`, `Pillow` (see `requirements.txt`).
- Missing but used: `pillow-heif` (add to `requirements.txt`).
- No tests, no CI config detected — run manual tests locally.

## Where to look for changes
- `app.py` — primary logic: upload flow, EXIF handling, DB access, routes.
- `templates/` — UI; careful with index-based tuple access.
- `static/icons/` and `static/uploads/` — assets.

## Suggested next small improvements (actionable)
- Add `pillow-heif` to `requirements.txt`.
- Fix DB schema mismatch in `init_db()` or the INSERT statements (choose one canonical schema).
- Add a small README or `CONTRIBUTING.md` with run steps and the missing dependency note.

---
If you'd like, I can:
- add `pillow-heif` to `requirements.txt`, or
- open a PR to fix the DB schema mismatch and add a simple test harness to exercise uploads.
Which should I do next?