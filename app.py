import os
import sqlite3
from flask import Flask, request, redirect, url_for, render_template
from werkzeug.utils import secure_filename
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import pillow_heif
from PIL import ImageOps
from datetime import datetime

pillow_heif.register_heif_opener()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
ALLOWED_CATEGORIES = ["Burg", "Fels", "Kirche", "Aussicht"]




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
    c.execute('''CREATE TABLE IF NOT EXISTS images (
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
    )''')
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

    conn.commit()
    conn.close()

init_db()


# --- Upload Route ---
@app.route('/upload', methods=['GET', 'POST'])
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

@app.route('/delete/<int:image_id>', methods=['GET', 'POST'])
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

    if request.method == 'POST':
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

    conn.close()
    return render_template('delete_confirm.html', image_id=image_id, filepath=filepath, title="Bild löschen")

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



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)