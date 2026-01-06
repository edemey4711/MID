import os
import sqlite3
from flask import Flask, request, redirect, url_for, render_template
from werkzeug.utils import secure_filename
import uuid
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import pillow_heif
from PIL import ImageOps
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session, flash
from flask_wtf.csrf import CSRFProtect
from functools import wraps
from flask import session, redirect, url_for, request, abort

pillow_heif.register_heif_opener()

app = Flask(__name__)
# Use an environment variable in production. Fallback to a random key for dev.
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

# Enable CSRF protection
csrf = CSRFProtect(app)

app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max file size
ALLOWED_CATEGORIES = ["Burg", "Fels", "Kirche", "Aussicht"]

# Cookie security flags (dev-safe defaults; enable Secure on prod)
_secure_cookie = os.environ.get('SESSION_COOKIE_SECURE')
is_secure = (_secure_cookie in ('1', 'true', 'True')) or (os.environ.get('FLASK_ENV') == 'production')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=is_secure
)


def _build_csp():
    return (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
        "style-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )


@app.after_request
def set_security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
    resp.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    resp.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    resp.headers['Content-Security-Policy'] = _build_csp()
    if is_secure:
        resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    return resp




# --- EXIF Hilfsfunktionen ---
def get_exif_data(image):
    exif_data = {}
    info = image._getexif()
    if info:
        for tag, value in info.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                gps_data = {}
                for t in value:
                    sub_decoded = GPSTAGS.get(t, t)
                    gps_data[sub_decoded] = value[t]
                exif_data[decoded] = gps_data
            else:
                exif_data[decoded] = value
    return exif_data


def convert_to_degrees(value):
    """Konvertiert EXIF GPS Werte in Dezimalgrad (robust für alle Formate)"""
    def to_float(x):
        if isinstance(x, tuple):
            return x[0] / x[1]
        return float(x)

    d = to_float(value[0])
    m = to_float(value[1])
    s = to_float(value[2])

    return d + (m / 60.0) + (s / 3600.0)


def get_lat_lon(exif_data):
    """Liest GPS Koordinaten robust und korrekt aus"""
    if "GPSInfo" not in exif_data:
        return None, None

    gps_info = exif_data["GPSInfo"]

    try:
        lat = convert_to_degrees(gps_info["GPSLatitude"])
        lon = convert_to_degrees(gps_info["GPSLongitude"])

        lat_ref = gps_info["GPSLatitudeRef"]
        lon_ref = gps_info["GPSLongitudeRef"]

        # Bytestrings in Strings umwandeln
        if isinstance(lat_ref, bytes):
            lat_ref = lat_ref.decode()
        if isinstance(lon_ref, bytes):
            lon_ref = lon_ref.decode()

        lat_ref = lat_ref.upper()
        lon_ref = lon_ref.upper()

        # Süd und West sind negativ
        if lat_ref == "S":
            lat = -lat
        if lon_ref == "W":
            lon = -lon

        return lat, lon

    except Exception:
        return None, None


# --- Datenbank initialisieren (erzeugt oder migriert bei Bedarf) ---
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # Erzeuge die Tabelle mit dem kanonischen Schema, falls sie nicht existiert
    conn.execute("""
    CREATE TABLE IF NOT EXISTS images (
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
    """)
    # ensure users table exists
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'uploader'
    )
    """)
    conn.commit()

    # Falls die Tabelle aus einer älteren Version vorhanden ist, fügen wir fehlende Spalten hinzu
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(images)").fetchall()]
    needed = {
        "latitude": "REAL",
        "longitude": "REAL",
        "upload_date": "TEXT",
        "upload_time": "TEXT",
        "exif_date": "TEXT",
        "exif_time": "TEXT",
    }

    for col, coltype in needed.items():
        if col not in existing_cols:
            try:
                c.execute(f"ALTER TABLE images ADD COLUMN {col} {coltype}")
            except Exception:
                # Best effort: falls ALTER TABLE fehlschlägt, fahren wir fort
                pass

    conn.close()

init_db()



# --- Login-Logout Hilfsfunktionen ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def deco(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return deco


# --- Upload Route ---
@app.route('/upload', methods=['GET', 'POST'])
@login_required
@role_required('uploader','admin')
def upload():
    if request.method == 'POST':
        name = request.form['name']
        if not name: 
            return "Bitte einen Namen eingeben.", 400
        description = request.form['description']
        category = request.form['category']

        if category not in ALLOWED_CATEGORIES:
            return "Ungültige Kategorie", 400

        image = request.files['image']

        if image:
            filename = secure_filename(image.filename)
            ext = filename.rsplit('.', 1)[-1].lower()

            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            # --- Validate file extension ---
            if ext not in ["jpg", "jpeg", "png", "gif", "heic", "heif", "webp"]:
                return "Nicht unterstütztes Bildformat. Erlaubt: JPG, PNG, GIF, HEIC, WebP", 400

            # --- Generate secure unique filename ---
            secure_base = secure_filename(image.filename.rsplit('.', 1)[0]) or "image"
            filename = f"{uuid.uuid4().hex}_{secure_base}.{ext}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            exif_data = {}
            lat, lon = None, None
            exif_date = None
            exif_time = None

            # --- HEIC / HEIF ---
            if ext in ["heic", "heif"]:
                heif_file = pillow_heif.read_heif(image.read())

                pil_img = Image.frombytes(
                    heif_file.mode,
                    heif_file.size,
                    heif_file.data,
                    "raw"
                )
                pil_img = ImageOps.exif_transpose(pil_img)

                exif_bytes = heif_file.info.get("exif", None)

                filename = filename.rsplit('.', 1)[0] + ".jpg"
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                if exif_bytes:
                    pil_img.save(path, "JPEG", quality=95, exif=exif_bytes)
                else:
                    pil_img.save(path, "JPEG", quality=95)

            else:
                image.save(path)

            # --- EXIF aus JPG auslesen ---
            try:
                # Verify it's a valid image
                verify_img = Image.open(path)
                verify_img.verify()

                pil_img_for_exif = Image.open(path)
                exif_data = get_exif_data(pil_img_for_exif)
                lat, lon = get_lat_lon(exif_data)

                # EXIF Datum/Zeit auslesen
                if "DateTimeOriginal" in exif_data:
                    dt = exif_data["DateTimeOriginal"]  # Format: "2023:08:15 14:32:10"
                    try:
                        exif_date, exif_time = dt.split(" ")
                        exif_date = exif_date.replace(":", "-")  # schöneres Format
                    except:
                        exif_date = None
                        exif_time = None

            except Exception:
                exif_data = {}
                lat, lon = None, None

            # Fallback Koordinaten
            if lat is None:
                lat = 51.1657
            if lon is None:
                lon = 10.4515

            # --- Upload Datum/Zeit ---
            now = datetime.now()
            upload_date = now.strftime("%Y-%m-%d")
            upload_time = now.strftime("%H:%M:%S")

            # --- In DB speichern ---
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("""
                INSERT INTO images 
                (name, description, category, filepath, latitude, longitude,
                 upload_date, upload_time, exif_date, exif_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, description, category, path, lat, lon,
                  upload_date, upload_time, exif_date, exif_time))
            conn.commit()
            conn.close()

        return redirect(url_for('map'))

    return render_template('upload.html', title="Bild hochladen")



# --- Map Route ---
@app.route('/map')
def map():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, name, description, category, filepath, latitude, longitude FROM images")
    images = c.fetchall()
    conn.close()
    return render_template('map.html', images=images, title="Karte")

@app.route('/gallery')
def gallery():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, name, description, category, filepath, latitude, longitude FROM images")
    images = c.fetchall()
    conn.close()
    return render_template('gallery.html', images=images, title="Galerie")

@app.route('/edit/<int:image_id>', methods=['GET', 'POST'])
@login_required
@role_required('uploader','admin')
def edit(image_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        category = request.form['category']
        if category not in ALLOWED_CATEGORIES:
            return "Ungültige Kategorie", 400

        lat = request.form['lat']
        lng = request.form['lng']

        c.execute("""
            UPDATE images
            SET name = ?, description = ?, category = ?, latitude = ?, longitude = ?
            WHERE id = ?
        """, (name, description, category, lat, lng, image_id))

        conn.commit()
        conn.close()
        return redirect(url_for('map'))

    # GET → Daten laden
    c.execute("SELECT id, name, description, category, filepath, latitude, longitude FROM images WHERE id = ?", (image_id,))
    image = c.fetchone()
    conn.close()

    return render_template('edit.html', image=image, title="Bild bearbeiten")

@app.route('/delete/<int:image_id>', methods=['POST'])
@login_required
@role_required('uploader','admin')
def delete(image_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # Bilddaten laden
    c.execute("SELECT filepath FROM images WHERE id = ?", (image_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return redirect(url_for('gallery'))

    filepath = row[0]

    # Datei löschen, falls vorhanden
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except:
            pass

    # DB-Eintrag löschen
    c.execute("DELETE FROM images WHERE id = ?", (image_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('gallery'))


@app.route('/detail/<int:image_id>')
def detail(image_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("""
        SELECT id, name, description, category, filepath, latitude, longitude,
               upload_date, upload_time, exif_date, exif_time
        FROM images WHERE id = ?
    """, (image_id,))
    img = c.fetchone()
    conn.close()

    if not img:
        return redirect(url_for('gallery'))

    return render_template('detail.html', img=img, title="Bilddetails")



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = get_user_by_username(request.form['username'])
        if user and check_password_hash(user['password_hash'], request.form['password']):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(request.args.get('next') or url_for('gallery'))
        flash('Ungültiger Benutzername oder Passwort', 'danger')
    return render_template('login.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    app.logger.debug("Logout aufgerufen; Session vorher: %s", dict(session))
    session.clear()
    resp = redirect(url_for('gallery'))
    cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
    resp.delete_cookie(cookie_name)
    flash('Erfolgreich ausgeloggt', 'success')
    return resp

def get_user_by_username(username):
    conn = sqlite3.connect('database.db')
    cur = conn.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row and {'id': row[0], 'username': row[1], 'password_hash': row[2], 'role': row[3]}

def create_user(username, password, role='uploader'):
    pw = generate_password_hash(password)
    conn = sqlite3.connect('database.db')
    conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)", (username, pw, role))
    conn.commit()
    conn.close()

# Ensure default admin user on import (after helpers are defined)
try:
    admin = get_user_by_username('admin')
    if not admin:
        create_user('admin', 'admin123', 'admin')
        app.logger.info("Default admin user created: admin/admin123")
except Exception as e:
    app.logger.warning(f"ensure_admin_user: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1')
    app.run(host='0.0.0.0', port=port, debug=debug)