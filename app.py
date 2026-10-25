# EcoTag IITR v2 - add/edit/delete entries from the browser, QR codes, map, printable QR sheet
import sqlite3, io, random, os, socket
from datetime import date
from flask import Flask, g, abort, request, redirect, url_for, render_template, send_file
import qrcode

DB = "ecotag.db"
app = Flask(__name__)
KINDS = ["tree", "dog", "cat", "other"]

# ---------- DATABASE ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL, name TEXT NOT NULL, species TEXT NOT NULL,
        status TEXT, notes TEXT, last_update TEXT,
        lat REAL, lon REAL, tagged INTEGER DEFAULT 0)""")
    if db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0:   # seed dummy data once
        trees = ["Neem", "Peepal", "Mango", "Gulmohar", "Ashoka"]
        for i in range(8):
            db.execute("INSERT INTO entries (kind,name,species,status,notes,last_update,lat,lon) VALUES (?,?,?,?,?,?,?,?)",
                ("tree", f"Tree-{i+1}", random.choice(trees), random.choice(["Fertilized", "Pesticide applied", "No treatment"]),
                 "Sample data", str(date.today()), 29.8649 + random.uniform(-.004, .004), 77.8965 + random.uniform(-.004, .004)))
        for i in range(4):
            k = random.choice(["dog", "cat"])
            db.execute("INSERT INTO entries (kind,name,species,status,notes,last_update,lat,lon) VALUES (?,?,?,?,?,?,?,?)",
                (k, f"{k.title()}-{i+1}", "Indian pariah" if k == "dog" else "Domestic shorthair",
                 random.choice(["Vaccinated + Sterilized", "Vaccinated only", "Not vaccinated"]),
                 "Sample data", str(date.today()), 29.8649 + random.uniform(-.004, .004), 77.8965 + random.uniform(-.004, .004)))
    db.commit(); db.close()

def species_list():
    return [r[0] for r in get_db().execute("SELECT DISTINCT species FROM entries ORDER BY species")]

def form_data():
    f = request.form
    return (f["kind"], f["name"].strip(), f["species"].strip(), f.get("status", "").strip(),
            f.get("notes", "").strip(), str(date.today()), float(f["lat"]), float(f["lon"]))

def base_url():
    """Address the QR codes point to. Must be reachable from the PHONE, so never localhost."""
    env = os.environ.get("BASE_URL")
    if env:
        return env.rstrip("/")
    host = request.host.split(":")[0]
    if host in ("localhost", "127.0.0.1"):
        try:
            t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); t.connect(("8.8.8.8", 80))
            ip = t.getsockname()[0]; t.close()
            return f"http://{ip}:{request.host.split(':')[-1] if ':' in request.host else 80}"
        except OSError:
            pass
    return request.host_url.rstrip("/")

@app.context_processor
def inject_base():
    return {"qr_base": base_url()}

# ---------- PAGES ----------
@app.route("/")
def dashboard():
    q = request.args.get("q", "").strip()
    kind = request.args.get("kind", "")
    sql, args = "SELECT * FROM entries WHERE 1=1", []
    if q:
        sql += " AND (name LIKE ? OR species LIKE ? OR status LIKE ?)"; args += [f"%{q}%"] * 3
    if kind:
        sql += " AND kind=?"; args.append(kind)
    rows = get_db().execute(sql + " ORDER BY id DESC", args).fetchall()
    all_rows = get_db().execute("SELECT kind, tagged FROM entries").fetchall()
    stats = {"total": len(all_rows), "tagged": sum(r["tagged"] for r in all_rows)}
    for k in KINDS: stats[k] = sum(1 for r in all_rows if r["kind"] == k)
    return render_template("index.html", rows=rows, q=q, kind=kind, kinds=KINDS, stats=stats)

@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        get_db().execute("INSERT INTO entries (kind,name,species,status,notes,last_update,lat,lon) VALUES (?,?,?,?,?,?,?,?)", form_data())
        get_db().commit()
        return redirect(url_for("dashboard"))
    return render_template("form.html", e=None, kinds=KINDS, species=species_list())

@app.route("/edit/<int:i>", methods=["GET", "POST"])
def edit(i):
    e = get_db().execute("SELECT * FROM entries WHERE id=?", (i,)).fetchone() or abort(404)
    if request.method == "POST":
        get_db().execute("UPDATE entries SET kind=?,name=?,species=?,status=?,notes=?,last_update=?,lat=?,lon=? WHERE id=?", form_data() + (i,))
        get_db().commit()
        return redirect(url_for("dashboard"))
    return render_template("form.html", e=e, kinds=KINDS, species=species_list())

@app.route("/delete/<int:i>", methods=["POST"])
def delete(i):
    get_db().execute("DELETE FROM entries WHERE id=?", (i,)); get_db().commit()
    return redirect(url_for("dashboard"))

@app.route("/toggle/<int:i>", methods=["POST"])
def toggle(i):
    get_db().execute("UPDATE entries SET tagged = 1 - tagged WHERE id=?", (i,)); get_db().commit()
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/entry/<int:i>")          # the page a QR scan lands on
def entry(i):
    e = get_db().execute("SELECT * FROM entries WHERE id=?", (i,)).fetchone() or abort(404)
    return render_template("entry.html", e=e)

@app.route("/qr/<int:i>.png")
def qr(i):
    img = qrcode.make(base_url() + f"/entry/{i}")
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/map")
def map_view():
    rows = get_db().execute("SELECT * FROM entries").fetchall()
    return render_template("map.html", rows=[dict(r) for r in rows])

@app.route("/print")
def print_sheet():
    rows = get_db().execute("SELECT * FROM entries ORDER BY id").fetchall()
    return render_template("print.html", rows=rows)

if __name__ == "__main__":
    init_db()
    print("Running at http://localhost:5000  (open it on your phone via your laptop's IP for QR scanning)")
    app.run(host="0.0.0.0", port=5000, debug=False)
