import os
import sqlite3
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash, jsonify
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "pdf", "svg"}
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = "change_me_secret"
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)

# ---------------- Helpers ----------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    # Pages
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            image_path TEXT
        )
    """)
    # Page PDFs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS page_pdfs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            title TEXT NOT NULL,
            FOREIGN KEY(page_id) REFERENCES pages(id)
        )
    """)
    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    cur.execute("INSERT OR IGNORE INTO users(username,password) VALUES('admin','admin')")

    # Buttons
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buttons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            color TEXT,
            page_id INTEGER,
            icon_path TEXT,
            position INTEGER DEFAULT 0,
            FOREIGN KEY(page_id) REFERENCES pages(id)
        )
    """)
    conn.commit()
    conn.close()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def save_file(file):
    if file and getattr(file, "filename", "") and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(UPLOAD_DIR / filename)
        return filename
    return None

def delete_uploaded_file(safe_filename: str):
    if not safe_filename:
        return
    try:
        os.remove(os.path.join(app.config["UPLOAD_FOLDER"], safe_filename))
    except FileNotFoundError:
        pass

@app.context_processor
def inject_theme():
    return {"current_theme": "light"}

# ---------------- Authentication ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","")
        password = request.form.get("password","")
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()
        if row:
            session["auth"] = True
            return redirect(url_for("admin"))
        flash("Неверный логин или пароль")
    return render_template("admin_login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def require_auth():
    if not session.get("auth"):
        return redirect(url_for("login"))
    return None

# ---------------- Kiosk ----------------
@app.route("/kiosk")
def kiosk():
    conn = db()
    buttons = conn.execute("SELECT * FROM buttons ORDER BY position ASC").fetchall()
    conn.close()
    return render_template("kiosk.html", buttons=buttons)

@app.route("/page/<int:pid>")
def page(pid):
    conn = db()
    p = conn.execute("SELECT * FROM pages WHERE id=?", (pid,)).fetchone()
    pdfs = conn.execute("SELECT * FROM page_pdfs WHERE page_id=?", (pid,)).fetchall()
    conn.close()
    if not p:
        return "Страница не найдена", 404
    return render_template("page.html", page=dict(p), pdfs=pdfs)

# ---------------- Admin Dashboard ----------------
@app.route("/admin")
def admin():
    redir = require_auth()
    if redir: return redir
    conn = db()
    pages = conn.execute("SELECT * FROM pages ORDER BY id DESC").fetchall()
    buttons = conn.execute("SELECT * FROM buttons ORDER BY position ASC").fetchall()
    conn.close()
    return render_template("admin_dashboard.html", pages=pages, buttons=buttons)

# ---------------- Pages CRUD ----------------
@app.route("/admin/page/create", methods=["POST"])
def admin_page_create():
    redir = require_auth()
    if redir: return redir

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "")
    image_file = request.files.get("image")

    pdf_files = request.files.getlist("pdfs[]")
    pdf_titles = request.form.getlist("pdf_titles[]")

    conn = db()
    cur = conn.cursor()

    image_path = save_file(image_file)
    cur.execute(
        "INSERT INTO pages(title, content, image_path) VALUES (?, ?, ?)",
        (title, content, image_path),
    )
    page_id = cur.lastrowid

    for i, pdf_file in enumerate(pdf_files):
        if pdf_file and getattr(pdf_file, "filename", ""):
            filename = save_file(pdf_file)
            custom_title = ""
            if i < len(pdf_titles):
                custom_title = (pdf_titles[i] or "").strip()
            pdf_title = custom_title if custom_title else os.path.splitext(pdf_file.filename)[0]
            cur.execute(
                "INSERT INTO page_pdfs(page_id, file_path, title) VALUES (?, ?, ?)",
                (page_id, filename, pdf_title),
            )

    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/admin/page/edit/<int:pid>", methods=["GET", "POST"])
def admin_page_edit(pid):
    redir = require_auth()
    if redir: return redir

    conn = db()
    page_row = conn.execute("SELECT * FROM pages WHERE id=?", (pid,)).fetchone()
    if not page_row:
        conn.close()
        return "Страница не найдена", 404

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "")
        image_file = request.files.get("image")

        pdf_files = request.files.getlist("pdfs[]")
        pdf_titles = request.form.getlist("pdf_titles[]")

        updates = {"title": title, "content": content}
        image_path = save_file(image_file)
        if image_path:
            updates["image_path"] = image_path

        set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
        vals = list(updates.values()) + [pid]
        conn.execute(f"UPDATE pages SET {set_clause} WHERE id=?", vals)

        for i, pdf_file in enumerate(pdf_files):
            if pdf_file and getattr(pdf_file, "filename", ""):
                filename = save_file(pdf_file)
                custom_title = ""
                if i < len(pdf_titles):
                    custom_title = (pdf_titles[i] or "").strip()
                pdf_title = custom_title if custom_title else os.path.splitext(pdf_file.filename)[0]
                conn.execute(
                    "INSERT INTO page_pdfs(page_id, file_path, title) VALUES (?, ?, ?)",
                    (pid, filename, pdf_title),
                )

        conn.commit()
        conn.close()

        # <<< вот здесь изменено, остаёмся на странице редактирования
        return redirect(url_for("admin_page_edit", pid=pid))

    pdfs = conn.execute("SELECT * FROM page_pdfs WHERE page_id=?", (pid,)).fetchall()
    conn.close()
    return render_template("admin_page_edit.html", page=dict(page_row), pdfs=pdfs)


@app.route("/admin/page/delete/<int:pid>", methods=["POST"])
def admin_page_delete(pid):
    redir = require_auth()
    if redir: return redir

    conn = db()
    pdfs = conn.execute("SELECT file_path FROM page_pdfs WHERE page_id=?", (pid,)).fetchall()
    for row in pdfs:
        delete_uploaded_file(row["file_path"])
    conn.execute("DELETE FROM page_pdfs WHERE page_id=?", (pid,))

    img = conn.execute("SELECT image_path FROM pages WHERE id=?", (pid,)).fetchone()
    if img and img["image_path"]:
        delete_uploaded_file(img["image_path"])

    conn.execute("DELETE FROM pages WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/admin/page/pdf/delete/<int:pdf_id>", methods=["POST"])
def admin_page_pdf_delete(pdf_id):
    redir = require_auth()
    if redir: return redir

    conn = db()
    pdf = conn.execute("SELECT * FROM page_pdfs WHERE id=?", (pdf_id,)).fetchone()
    if pdf:
        delete_uploaded_file(pdf["file_path"])
        conn.execute("DELETE FROM page_pdfs WHERE id=?", (pdf_id,))
        conn.commit()
    conn.close()
    return jsonify({"success": True})

# ---------------- Buttons CRUD ----------------
@app.route("/admin/button/create", methods=["POST"])
def admin_button_create():
    redir = require_auth()
    if redir: return redir

    title = request.form.get("title")
    color = request.form.get("color")
    page_id = request.form.get("page_id")
    icon_file = request.files.get("icon")

    icon_path = save_file(icon_file)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO buttons(title,color,page_id,icon_path) VALUES (?,?,?,?)",
        (title, color, page_id, icon_path),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/admin/button/update/<int:bid>", methods=["POST"])
def admin_button_update(bid):
    redir = require_auth()
    if redir: return redir

    title = request.form.get("title")
    color = request.form.get("color")
    page_id = request.form.get("page_id")
    icon_file = request.files.get("icon")
    icon_path = save_file(icon_file) if icon_file else None

    conn = db()
    cur = conn.cursor()
    updates = {"title": title, "color": color, "page_id": page_id}
    if icon_path:
        updates["icon_path"] = icon_path
    set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
    vals = list(updates.values()) + [bid]
    cur.execute(f"UPDATE buttons SET {set_clause} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/button/delete/<int:bid>", methods=["POST"])
def admin_button_delete(bid):
    redir = require_auth()
    if redir: return redir
    conn = db()
    conn.execute("DELETE FROM buttons WHERE id=?", (bid,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/admin/button/reorder", methods=["POST"])
def admin_button_reorder():
    redir = require_auth()
    if redir: return redir
    data = request.get_json()
    conn = db()
    for item in data:
        conn.execute("UPDATE buttons SET position=? WHERE id=?", (item['position'], item['id']))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/page/<int:pid>/delete_pdf/<int:pdf_id>", methods=["POST"])
def delete_pdf(pid, pdf_id):
    conn = db()
    conn.execute("DELETE FROM pdfs WHERE id=? AND page_id=?", (pdf_id, pid))
    conn.commit()
    conn.close()
    flash("PDF удалён", "success")
    return redirect(url_for("admin_page_edit", pid=pid))


# ---------------- File Uploads ----------------
@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ---------------- TinyMCE Image Upload ----------------
@app.route("/upload_image", methods=["POST"])
def upload_image():
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file"}), 400

    filename = save_file(file)
    if not filename:
        return jsonify({"error": "File type not allowed"}), 400

    file_url = url_for("uploads", filename=filename)
    return jsonify({"location": file_url})

# ---------------- Root ----------------
@app.route("/")
def root():
    return redirect(url_for("kiosk"))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
