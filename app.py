import os
import sqlite3
from flask import Flask, request, redirect, url_for, render_template, send_from_directory, session, flash, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import pillow_heif
from PIL import ImageOps
from datetime import datetime
from flask_wtf.csrf import CSRFProtect
from functools import wraps

pillow_heif.register_heif_opener()

app = Flask(__name__)
# Use an environment variable in production. Fallback to a random key for dev.
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

# Database path: use /data on Railway (with volume), fallback to local for dev
DB_PATH = '/data/database.db' if os.path.exists('/data') else 'database.db'

# Upload folder: use /data/uploads on Railway (with volume), fallback to static/uploads for dev
UPLOAD_FOLDER = '/data/uploads' if os.path.exists('/data') else 'static/uploads'

# Thumbnail folder: use /data/thumbnails on Railway, fallback to static/thumbnails for dev
THUMBNAIL_FOLDER = '/data/thumbnails' if os.path.exists('/data') else 'static/thumbnails'

# Enable CSRF protection
csrf = CSRFProtect(app)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['THUMBNAIL_FOLDER'] = THUMBNAIL_FOLDER
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
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://*.tile.opentopomap.org https://server.arcgisonline.com; "
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


def create_thumbnail(source_path, thumbnail_path, size=(400, 400)):
    """
    Erstellt ein Thumbnail für ein Bild.
    
    Args:
        source_path: Pfad zum Originalbild
        thumbnail_path: Pfad wo das Thumbnail gespeichert werden soll
        size: Maximale Größe als Tuple (Breite, Höhe)
    
    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    try:
        with Image.open(source_path) as img:
            # Korrigiere Orientierung basierend auf EXIF
            img = ImageOps.exif_transpose(img)
            
            # Erstelle Thumbnail (behält Seitenverhältnis bei)
            img.thumbnail(size, Image.Resampling.LANCZOS)
            
            # Speichere als JPEG (auch wenn Original PNG/WebP war)
            img.convert('RGB').save(thumbnail_path, 'JPEG', quality=85, optimize=True)
            
        return True
    except Exception as e:
        app.logger.error(f"Fehler beim Erstellen des Thumbnails für {source_path}: {e}")
        return False


# --- Datenbank initialisieren (erzeugt oder migriert bei Bedarf) ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Erzeuge die Tabelle mit dem kanonischen Schema, falls sie nicht existiert
    conn.execute("""
    CREATE TABLE IF NOT EXISTS images (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      description TEXT,
      category TEXT,
      filepath TEXT NOT NULL,
      thumbnail_path TEXT,
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
        "thumbnail_path": "TEXT",
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



# --- Serve uploaded images from volume ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded images from UPLOAD_FOLDER (which may be in /data/uploads on Railway)"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# --- Serve thumbnails ---
@app.route('/thumbnails/<filename>')
def thumbnail_file(filename):
    """Serve thumbnail images from THUMBNAIL_FOLDER"""
    return send_from_directory(app.config['THUMBNAIL_FOLDER'], filename)


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
                    except Exception as e:
                        app.logger.warning(f"Fehler beim Parsen des EXIF-Datums: {e}")
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

            # --- Thumbnail erstellen ---
            os.makedirs(app.config['THUMBNAIL_FOLDER'], exist_ok=True)
            
            # Thumbnail bekommt denselben Namen wie das Original (aber als .jpg)
            thumb_filename = os.path.splitext(filename)[0] + '_thumb.jpg'
            thumb_path = os.path.join(app.config['THUMBNAIL_FOLDER'], thumb_filename)
            
            # Erstelle Thumbnail
            thumbnail_created = create_thumbnail(path, thumb_path)
            
            # Wenn Thumbnail-Erstellung fehlschlägt, setze None
            if not thumbnail_created:
                thumb_filename = None

            # --- In DB speichern (nur Dateiname, nicht voller Pfad) ---
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                INSERT INTO images 
                (name, description, category, filepath, thumbnail_path, latitude, longitude,
                 upload_date, upload_time, exif_date, exif_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, description, category, filename, thumb_filename, lat, lon,
                  upload_date, upload_time, exif_date, exif_time))
            conn.commit()
            conn.close()

        return redirect(url_for('map'))

    return render_template('upload.html', title="Bild hochladen")



# --- Map Route ---
@app.route('/')
@app.route('/map')
def map():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, description, category, filepath, thumbnail_path, latitude, longitude FROM images")
    images = c.fetchall()
    conn.close()
    return render_template('map.html', images=images, title="Karte")

@app.route('/gallery')
def gallery():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, description, category, filepath, thumbnail_path, latitude, longitude FROM images")
    images = c.fetchall()
    conn.close()
    return render_template('gallery.html', images=images, title="Galerie")

@app.route('/edit/<int:image_id>', methods=['GET', 'POST'])
@login_required
@role_required('uploader','admin')
def edit(image_id):
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Bilddaten laden (inkl. Thumbnail-Pfad)
    c.execute("SELECT filepath, thumbnail_path FROM images WHERE id = ?", (image_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return redirect(url_for('gallery'))

    filepath = row[0]
    thumbnail_path = row[1]

    # Hauptdatei löschen, falls vorhanden
    if filepath:
        full_path = os.path.join(app.config['UPLOAD_FOLDER'], filepath)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except Exception as e:
                app.logger.warning(f"Fehler beim Löschen der Datei {filepath}: {e}")

    # Thumbnail löschen, falls vorhanden
    if thumbnail_path:
        thumb_full_path = os.path.join(app.config['THUMBNAIL_FOLDER'], thumbnail_path)
        if os.path.exists(thumb_full_path):
            try:
                os.remove(thumb_full_path)
            except Exception as e:
                app.logger.warning(f"Fehler beim Löschen des Thumbnails {thumbnail_path}: {e}")

    # DB-Eintrag löschen
    c.execute("DELETE FROM images WHERE id = ?", (image_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('gallery'))


@app.route('/detail/<int:image_id>')
def detail(image_id):
    conn = sqlite3.connect(DB_PATH)
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
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
        app.logger.info(f"Login attempt for username: {username}")
        
        user = get_user_by_username(username)
        if not user:
            app.logger.warning(f"User not found: {username}")
            flash('Ungültiger Benutzername oder Passwort', 'danger')
            return render_template('login.html')
        
        app.logger.info(f"User found: {username}, checking password...")
        
        if check_password_hash(user['password_hash'], password):
            app.logger.info(f"Password correct for {username}, setting session...")
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            app.logger.info(f"Session set: {dict(session)}")
            return redirect(request.args.get('next') or url_for('gallery'))
        else:
            app.logger.warning(f"Password incorrect for {username}")
            flash('Ungültiger Benutzername oder Passwort', 'danger')
    
    return render_template('login.html')

@app.route('/reset-admin/<token>')
def reset_admin(token):
    """One-time admin reset endpoint. Set ADMIN_RESET_TOKEN env var to use."""
    required_token = os.environ.get('ADMIN_RESET_TOKEN', '')
    if not required_token or token != required_token:
        abort(404)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM users WHERE username = ?", ('admin',))
        conn.commit()
        conn.close()
        
        create_user('admin', 'admin123', 'admin')
        return "✅ Admin user reset! Username: admin, Password: admin123<br><br>Delete ADMIN_RESET_TOKEN env var now!"
    except Exception as e:
        return f"Error: {e}", 500

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
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row and {'id': row[0], 'username': row[1], 'password_hash': row[2], 'role': row[3]}

def create_user(username, password, role='uploader'):
    pw = generate_password_hash(password)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)", (username, pw, role))
    conn.commit()
    conn.close()

# Ensure default admin user on import (after helpers are defined)
try:
    force_reset = os.environ.get('RESET_ADMIN_PASSWORD', 'false').lower() == 'true'
    admin = get_user_by_username('admin')
    
    # Prüfe ob Admin mit korrektem Passwort existiert
    admin_password_correct = False
    if admin:
        admin_password_correct = check_password_hash(admin['password_hash'], 'admin123')
    
    # Wenn kein Admin existiert oder Passwort falsch ist, neu erstellen
    if force_reset or not admin or not admin_password_correct:
        if admin:
            # Delete existing (wrong password) admin
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM users WHERE username = ?", ('admin',))
            conn.commit()
            conn.close()
            if not admin_password_correct:
                app.logger.warning("Admin-User hatte falsches Passwort, wird neu erstellt")
            else:
                app.logger.info("Existing admin user deleted for reset")
        
        create_user('admin', 'admin123', 'admin')
        app.logger.info("✓ Default admin user created/reset: admin/admin123")
except Exception as e:
    app.logger.error(f"Error ensuring admin user: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1')
    app.run(host='0.0.0.0', port=port, debug=debug)