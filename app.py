# EcoTag IITR v4 - tagged entries + plant catalog + analytics + advanced map/frontend
import sqlite3, io, csv, json, math, random, os, socket, uuid, hmac
from datetime import date, timedelta
from functools import wraps
from flask import (Flask, g, abort, request, redirect, url_for, render_template,
                   send_file, session, flash, Response)
import qrcode

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "ecotag.db")
UPLOADS = os.path.join(BASE, "static", "uploads")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-before-deploying")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")   # set a real one before deploying!

# Removed "cat" and "other" from the tracked kinds
KINDS = ["tree", "dog"]
EVENT_TYPES = ["Vaccination", "Sterilization", "Fertilizer", "Pesticide", "Checkup", "Treatment", "Other"]
REPORT_KINDS = ["Injured", "Sick", "Aggressive", "Other"]
HABIT = {"T": "Tree", "S": "Shrub", "H": "Herb", "C": "Climber", "G": "Grass"}

# ---------- DATABASE ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB, timeout=30)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL, species TEXT NOT NULL,
        status TEXT, notes TEXT, last_update TEXT, lat REAL, lon REAL, tagged INTEGER DEFAULT 0, photo TEXT);
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, date TEXT, type TEXT, note TEXT, next_due TEXT);
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, date TEXT, kind TEXT, note TEXT, handled INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS species (
        id INTEGER PRIMARY KEY, sci TEXT, common TEXT, family TEXT, habit TEXT, uses TEXT, cat TEXT, loc TEXT, basis TEXT);
    """)
    try: db.execute("ALTER TABLE entries ADD COLUMN photo TEXT")      # upgrade older databases
    except sqlite3.OperationalError: pass
    
    # (re)load the plant catalog; safe to run repeatedly
    if os.path.exists(os.path.join(BASE, "species_data.json")):
        with open(os.path.join(BASE, "species_data.json"), encoding="utf-8") as f:
            for x in json.load(f):
                db.execute("INSERT OR REPLACE INTO species (id,sci,common,family,habit,uses,cat,loc,basis) VALUES (?,?,?,?,?,?,?,?,?)",
                           (x["no"], x["sci"], x["common"], x["family"], x["habit"], x["use"], x["cat"], x["loc"], x["basis"]))
    
    if db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0:  # seed demo data once
        today = date.today()
        
        # Exact tree coordinates mapped from the ECE Dept, IIT Roorkee
        ece_trees = [
            ("Tree 1", "ficus benghalensis", 29.863111, 77.895694, "tree1.jpeg"),
            ("Tree 2", "polyalthia longifolia", 29.863222, 77.895361, "tree2.jpeg"),
            ("Tree 3", "ficus religiosa", 29.863472, 77.895389, "tree3.jpeg"),
            ("Tree 4", "azadirachta indica", 29.863500, 77.895361, "tree4.jpeg"),
            ("Tree 5", "roystonea regia", 29.863556, 77.895361, "tree5.jpeg"),
            ("Tree 6", "alstonia scholaris", 29.863944, 77.895417, "tree6.jpeg"),
            ("Tree 7", "mangifera indica", 29.863917, 77.895500, "tree7.jpeg"),
            ("Tree 8", "platycladus orientalis", 29.863944, 77.895778, "tree8.jpeg"),
            ("Tree 9", "dalbergia sissoo", 29.863889, 77.896111, "tree9.jpeg"),
            ("Tree 10", "terminalia arjuna", 29.863667, 77.896139, "tree10.jpeg"),
            ("Tree 11", "tamarindus indica", 29.863556, 77.896083, "tree11.jpeg"),
            ("Tree 12", "bombax ceiba", 29.863528, 77.896028, "tree12.jpeg"),
            ("Tree 13", "butea monosperma", 29.863444, 77.896056, "tree13.jpeg"),
            ("Tree 14", "ficus racemosa", 29.863417, 77.896139, "tree14.jpeg")
        ]

        for name, species, lat, lon, photo in ece_trees:
            cur = db.execute(
                "INSERT INTO entries (kind,name,species,status,notes,last_update,lat,lon,photo) VALUES (?,?,?,?,?,?,?,?,?)",
                ("tree", name, species, "Active", "ECE Dept Campus Tree", str(today), lat, lon, photo)
            )
            
            if random.choice([True, False]):
                d = today - timedelta(days=random.randint(30, 200))
                db.execute("INSERT INTO events (entry_id,date,type,note,next_due) VALUES (?,?,?,?,?)",
                           (cur.lastrowid, str(d), "Fertilizer", "Routine maintenance", str(d + timedelta(days=120))))

        # Seed specific campus dogs with their photos
        campus_dogs = [
            ("Sheru", "Indian pariah", "dog1.png"),
            ("Brownie", "Indian pariah", "dog2.png"),
            ("Patch", "Indian pariah", "dog3.png"),
            ("Raju", "Indian pariah", "dog4.png"),
            ("Chotu", "Indian pariah", "dog5.png"),
            ("Snowy", "Labrador Retriever", "dog6.png"),
            ("Bhola", "Himalayan Sheepdog mix", "dog7.png"),
            ("Kalu", "Indian pariah", "dog8.png"),
            ("Lali", "Indian pariah", "dog9.png"),
            ("Moti", "Indian pariah", "dog10.png")
        ]

        for name, species, photo in campus_dogs:
            lat = 29.8635 + random.uniform(-.003, .003)
            lon = 77.8958 + random.uniform(-.003, .003)
            
            cur = db.execute(
                "INSERT INTO entries (kind,name,species,status,notes,last_update,lat,lon,photo) VALUES (?,?,?,?,?,?,?,?,?)",
                ("dog", name, species, "Active", "Campus community dog", str(today), lat, lon, photo)
            )
            
            d = today - timedelta(days=random.randint(30, 300))
            db.execute("INSERT INTO events (entry_id,date,type,note,next_due) VALUES (?,?,?,?,?)",
                       (cur.lastrowid, str(d), "Vaccination", "Anti-Rabies / 7-in-1", str(d + timedelta(days=365))))

    db.commit(); db.close()

# ---------- HELPERS ----------
def base_url():
    """Address the QR codes point to. Must be reachable from the PHONE, so never localhost."""
    env = os.environ.get("BASE_URL")
    if env: return env.rstrip("/")
    host = request.host.split(":")[0]
    if host in ("localhost", "127.0.0.1"):
        try:
            t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); t.connect(("8.8.8.8", 80))
            ip = t.getsockname()[0]; t.close()
            return f"http://{ip}:{request.host.split(':')[-1] if ':' in request.host else 80}"
        except OSError: pass
    return request.host_url.rstrip("/")

HERO_NAMES = ("thomason.jpg", "thomason.jpeg", "thomason.png", "thomason.webp")

@app.context_processor
def inject():
    return {"qr_base": base_url(), "is_admin": session.get("admin", False),
            "logo_exists": os.path.exists(os.path.join(BASE, "static", "iitr-logo.png")),
            "today": str(date.today()), "HABIT": HABIT, "path": request.path,
            "hero_photo": next((n for n in HERO_NAMES if os.path.exists(os.path.join(BASE, "static", n))), None)}

def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper

def save_photo():
    f = request.files.get("photo")
    if not f or not f.filename: return None
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"): return None
    name = uuid.uuid4().hex + "." + ext
    f.save(os.path.join(UPLOADS, name)); return name

def form_data():
    f = request.form
    return (f["kind"], f["name"].strip(), f["species"].strip(), f.get("status", "").strip(),
            f.get("notes", "").strip(), str(date.today()), float(f["lat"]), float(f["lon"]))

# ----- plant catalog helpers -----
# Local names people actually use -> scientific name in the catalog (the report uses other common names, e.g. Neem = "Indian Lilac")
ALIASES = {"neem": "azadirachta indica", "peepal": "ficus religiosa", "pipal": "ficus religiosa", "peepul": "ficus religiosa",
           "bargad": "ficus benghalensis", "sheesham": "dalbergia sissoo", "shisham": "dalbergia sissoo", "amaltas": "cassia fistula",
           "arjuna": "terminalia arjuna", "imli": "tamarindus indica", "amla": "phyllanthus emblica", "bel": "aegle marmelos",
           "aam": "mangifera indica", "semal": "bombax ceiba", "palash": "butea monosperma", "gular": "ficus racemosa",
           "eucalyptus": "eucalyptus camaldulensis", "polyalthia longifolia": "monoon longifolium", "nimbu": "citrus limonium", "lemon": "citrus limonium"}

def lookup():
    if "sp_lookup" not in g:
        m = {}
        for s in get_db().execute("SELECT * FROM species"):
            m[s["sci"].lower()] = s
            if s["common"]: m.setdefault(s["common"].lower(), s)
        for alias, sci in ALIASES.items():
            if sci in m: m.setdefault(alias, m[sci])
        g.sp_lookup = m
    return g.sp_lookup

def find_species(name):
    """Match free text to a catalog plant by scientific name, catalog common name, or a known local name (exact only)."""
    return lookup().get((name or "").strip().lower())

def species_list():
    names = {r[0] for r in get_db().execute("SELECT DISTINCT species FROM entries")}
    for s in get_db().execute("SELECT sci, common FROM species"):
        names.add(s["sci"])
        if s["common"]: names.add(s["common"])
    names |= {a.title() for a, sci in ALIASES.items() if sci in lookup()}
    return sorted(names, key=str.lower)

def annotate(rows):
    out = []
    for r in rows:
        d = dict(r); sp = find_species(d["species"])
        d["sp_id"] = sp["id"] if sp else None
        d["sp_sci"] = sp["sci"] if sp else ""
        d["sp_common"] = sp["common"] if sp else ""
        d["sp_uses"] = sp["uses"] if sp else ""
        d["photo_url"] = url_for("static", filename="uploads/" + d["photo"]) if d.get("photo") else ""
        out.append(d)
    return out

def haversine(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(x))

def bars(pairs):
    mx = max([v for _, v in pairs] or [1]) or 1
    return [{"label": k, "n": v, "pct": round(100 * v / mx)} for k, v in pairs]

# ---------- AUTH ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            nxt = request.args.get("next", "/")
            return redirect(nxt if nxt.startswith("/") else "/")
        flash("Wrong password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin", None); return redirect("/")

# ---------- ENTRIES ----------
@app.route("/")
def home():
    db = get_db()
    ents = annotate(db.execute("SELECT * FROM entries ORDER BY id").fetchall())
    stats = {"trees": sum(1 for e in ents if e["kind"] == "tree"), "dogs": sum(1 for e in ents if e["kind"] == "dog"),
             "plants": db.execute("SELECT COUNT(*) FROM species").fetchone()[0], "tagged": sum(e["tagged"] for e in ents)}
    trees = [e for e in ents if e["kind"] == "tree" and e["photo"]][:4]
    dogs = [e for e in ents if e["kind"] == "dog" and e["photo"]][:4]
    featured = [x for pair in zip(trees, dogs) for x in pair] + trees[len(dogs):] + dogs[len(trees):]
    return render_template("home.html", stats=stats, featured=featured)

@app.route("/explore")
def dashboard():
    db = get_db()
    rows = annotate(db.execute("SELECT * FROM entries ORDER BY id DESC").fetchall())
    stats = {"total": len(rows), "tagged": sum(r["tagged"] for r in rows),
             "reports": db.execute("SELECT COUNT(*) FROM reports WHERE handled=0").fetchone()[0]}
    for k in KINDS: stats[k] = sum(1 for r in rows if r["kind"] == k)
    due = db.execute("""SELECT e.id, e.name, e.kind, ev.type, ev.next_due FROM events ev JOIN entries e ON e.id = ev.entry_id
        WHERE ev.id = (SELECT id FROM events x WHERE x.entry_id = ev.entry_id AND x.type = ev.type ORDER BY date DESC, id DESC LIMIT 1)
        AND ev.next_due IS NOT NULL AND ev.next_due != '' AND ev.next_due <= date('now','+14 day')
        ORDER BY ev.next_due""").fetchall()
    stats["due"] = len(due)
    return render_template("index.html", rows=rows, q=request.args.get("q", ""), kind=request.args.get("kind", ""),
                           kinds=KINDS, stats=stats, due=due)

@app.route("/add", methods=["GET", "POST"])
@admin_required
def add():
    if request.method == "POST":
        get_db().execute("INSERT INTO entries (kind,name,species,status,notes,last_update,lat,lon,photo) VALUES (?,?,?,?,?,?,?,?,?)",
                         form_data() + (save_photo(),))
        get_db().commit(); flash("Entry added."); return redirect(url_for("dashboard"))
    return render_template("form.html", e=None, kinds=KINDS, species=species_list())

@app.route("/edit/<int:i>", methods=["GET", "POST"])
@admin_required
def edit(i):
    e = get_db().execute("SELECT * FROM entries WHERE id=?", (i,)).fetchone() or abort(404)
    if request.method == "POST":
        get_db().execute("UPDATE entries SET kind=?,name=?,species=?,status=?,notes=?,last_update=?,lat=?,lon=? WHERE id=?", form_data() + (i,))
        p = save_photo()
        if p: get_db().execute("UPDATE entries SET photo=? WHERE id=?", (p, i))
        get_db().commit(); flash("Entry saved."); return redirect(url_for("dashboard"))
    return render_template("form.html", e=e, kinds=KINDS, species=species_list())

@app.route("/delete/<int:i>", methods=["POST"])
@admin_required
def delete(i):
    for t, col in (("entries", "id"), ("events", "entry_id"), ("reports", "entry_id")):
        get_db().execute(f"DELETE FROM {t} WHERE {col}=?", (i,))
    get_db().commit(); flash("Entry deleted."); return redirect(url_for("dashboard"))

@app.route("/toggle/<int:i>", methods=["POST"])
@admin_required
def toggle(i):
    get_db().execute("UPDATE entries SET tagged = 1 - tagged WHERE id=?", (i,)); get_db().commit()
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/entry/<int:i>")
def entry(i):
    db = get_db()
    e = db.execute("SELECT * FROM entries WHERE id=?", (i,)).fetchone() or abort(404)
    events = db.execute("SELECT * FROM events WHERE entry_id=? ORDER BY date DESC, id DESC", (i,)).fetchall()
    others = annotate(db.execute("SELECT * FROM entries WHERE id != ?", (i,)).fetchall())
    for o in others: o["dist"] = haversine(e["lat"], e["lon"], o["lat"], o["lon"])
    nearby = sorted(others, key=lambda o: o["dist"])[:4]
    return render_template("entry.html", e=e, events=events, event_types=EVENT_TYPES, report_kinds=REPORT_KINDS,
                           sp=find_species(e["species"]), nearby=nearby)

@app.route("/event/<int:i>", methods=["POST"])
@admin_required
def add_event(i):
    f = request.form
    get_db().execute("INSERT INTO events (entry_id,date,type,note,next_due) VALUES (?,?,?,?,?)",
                     (i, f.get("date") or str(date.today()), f["type"], f.get("note", "").strip(), f.get("next_due", "")))
    get_db().execute("UPDATE entries SET status=?, last_update=? WHERE id=?", (f["type"], str(date.today()), i))
    get_db().commit(); flash("Care record added."); return redirect(url_for("entry", i=i))

@app.route("/event/delete/<int:ev>", methods=["POST"])
@admin_required
def del_event(ev):
    r = get_db().execute("SELECT entry_id FROM events WHERE id=?", (ev,)).fetchone() or abort(404)
    get_db().execute("DELETE FROM events WHERE id=?", (ev,)); get_db().commit()
    return redirect(url_for("entry", i=r["entry_id"]))

@app.route("/report/<int:i>", methods=["POST"])
def report(i):
    if request.form.get("kind") not in REPORT_KINDS: abort(400)
    get_db().execute("INSERT INTO reports (entry_id,date,kind,note) VALUES (?,?,?,?)",
                     (i, str(date.today()), request.form["kind"], request.form.get("note", "").strip()[:500]))
    get_db().commit(); flash("Thanks! Your report was sent to the campus care team.")
    return redirect(url_for("entry", i=i))

@app.route("/reports")
@admin_required
def reports():
    rows = get_db().execute("""SELECT r.*, e.name, e.kind AS ekind FROM reports r JOIN entries e ON e.id=r.entry_id
                               ORDER BY r.handled, r.date DESC, r.id DESC""").fetchall()
    return render_template("reports.html", rows=rows)

@app.route("/reports/resolve/<int:r>", methods=["POST"])
@admin_required
def resolve(r):
    get_db().execute("UPDATE reports SET handled=1 WHERE id=?", (r,)); get_db().commit()
    return redirect(url_for("reports"))

@app.route("/qr/<int:i>.png")
def qr(i):
    img = qrcode.make(base_url() + f"/entry/{i}")
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/map")
def map_view():
    rows = annotate(get_db().execute("""SELECT e.*, (SELECT COUNT(*) FROM reports r WHERE r.entry_id=e.id AND r.handled=0) AS open_reports
                                        FROM entries e""").fetchall())
    for r in rows: r["sp_uses"] = (r["sp_uses"] or "")[:120]
    return render_template("map.html", rows=rows)

@app.route("/print")
@admin_required
def print_sheet():
    return render_template("print.html", rows=annotate(get_db().execute("SELECT * FROM entries ORDER BY id").fetchall()))

@app.route("/export.csv")
@admin_required
def export_csv():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["id", "kind", "name", "species", "catalog_scientific_name", "catalog_common_name", "status", "last_update", "lat", "lon", "tag_placed"])
    for r in annotate(get_db().execute("SELECT * FROM entries ORDER BY id").fetchall()):
        w.writerow([r["id"], r["kind"], r["name"], r["species"], r["sp_sci"], r["sp_common"], r["status"], r["last_update"], r["lat"], r["lon"], r["tagged"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ecotag_entries.csv"})

# ---------- PLANT CATALOG ----------
def species_counts():
    counts = {}
    for (sp,) in get_db().execute("SELECT species FROM entries"):
        m = find_species(sp)
        if m: counts[m["id"]] = counts.get(m["id"], 0) + 1
    return counts

@app.route("/qr/species/<int:i>.png")
def qr_species(i):
    img = qrcode.make(base_url() + f"/species/{i}")
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/print/species")
@admin_required
def print_species():
    counts = species_counts()
    rows = [dict(r, tagged=counts.get(r["id"], 0)) for r in get_db().execute("SELECT * FROM species ORDER BY sci")]
    return render_template("print_species.html", rows=rows)

@app.route("/species")
def species_index():
    q = request.args.get("q", "").strip(); habit = request.args.get("habit", ""); cat = request.args.get("cat", "")
    sql = "SELECT s.* FROM species s WHERE 1=1"
    args = []
    if q:
        sql += " AND (sci LIKE ? OR common LIKE ? OR family LIKE ? OR uses LIKE ?)"; args += [f"%{q}%"] * 4
    if habit:
        sql += " AND habit=?"; args.append(habit)
    if cat:
        sql += " AND cat=?"; args.append(cat)
    rows = [dict(r) for r in get_db().execute(sql + " ORDER BY sci", args).fetchall()]
    counts = species_counts()
    for r in rows: r["tagged"] = counts.get(r["id"], 0)
    tag = request.args.get("tag", "")
    if tag == "tagged": rows = [r for r in rows if r["tagged"]]
    if tag == "untagged": rows = [r for r in rows if not r["tagged"]]
    covered = len(counts); total_species = get_db().execute("SELECT COUNT(*) FROM species").fetchone()[0]
    cats = [r[0] for r in get_db().execute("SELECT cat, COUNT(*) c FROM species GROUP BY cat ORDER BY c DESC")]
    return render_template("species.html", rows=rows, q=q, habit=habit, cat=cat, cats=cats, tag=tag, covered=covered, total_species=total_species)

@app.route("/species/<int:i>")
def species_one(i):
    s = get_db().execute("SELECT * FROM species WHERE id=?", (i,)).fetchone() or abort(404)
    tagged = [e for e in get_db().execute("SELECT * FROM entries ORDER BY id DESC").fetchall()
              if (find_species(e["species"]) or {"id": None})["id"] == s["id"]]
    return render_template("species_one.html", s=s, tagged=tagged)

@app.route("/api/species")
def api_species():
    sp = find_species(request.args.get("name", ""))
    if not sp: return {"found": False}
    return {"found": True, "id": sp["id"], "sci": sp["sci"], "common": sp["common"], "family": sp["family"],
            "habit": sp["habit"], "habit_label": HABIT.get(sp["habit"], sp["habit"]), "uses": sp["uses"],
            "cat": sp["cat"], "loc": sp["loc"], "basis": sp["basis"]}

# ---------- ANALYTICS ----------
@app.route("/analytics")
def analytics():
    db = get_db()
    ents = annotate(db.execute("SELECT * FROM entries").fetchall())
    n = len(ents); placed = sum(e["tagged"] for e in ents)
    kinds = bars([(k.title(), sum(1 for e in ents if e["kind"] == k)) for k in KINDS])
    sp_count = {}
    for e in ents:
        key = e["sp_common"] or e["sp_sci"] or e["species"]; sp_count[key] = sp_count.get(key, 0) + 1
    top_species = bars(sorted(sp_count.items(), key=lambda x: -x[1])[:8])
    matched = sum(1 for e in ents if e["sp_id"])
    today = str(date.today()); soon = str(date.today() + timedelta(days=14))
    latest = db.execute("""SELECT ev.next_due FROM events ev WHERE ev.id = (SELECT id FROM events x WHERE x.entry_id=ev.entry_id
                           AND x.type=ev.type ORDER BY date DESC, id DESC LIMIT 1) AND ev.next_due IS NOT NULL AND ev.next_due != ''""").fetchall()
    care = bars([("Overdue", sum(1 for r in latest if r[0] < today)),
                 ("Due within 14 days", sum(1 for r in latest if today <= r[0] <= soon)),
                 ("Up to date", sum(1 for r in latest if r[0] > soon))])
    rep = db.execute("SELECT kind, handled FROM reports").fetchall()
    rep_kinds = bars([(k, sum(1 for r in rep if r[0] == k)) for k in REPORT_KINDS])
    cat_habit = bars([(HABIT.get(r[0], r[0]), r[1]) for r in db.execute("SELECT habit, COUNT(*) FROM species GROUP BY habit ORDER BY 2 DESC")])
    cat_use = bars([(r[0], r[1]) for r in db.execute("SELECT cat, COUNT(*) FROM species GROUP BY cat ORDER BY 2 DESC")])
    cov = len(species_counts()); cov_total = db.execute("SELECT COUNT(*) FROM species").fetchone()[0]
    return render_template("analytics.html", cov=cov, cov_total=cov_total, cov_pct=round(100 * cov / cov_total) if cov_total else 0, n=n, placed=placed, pct=round(100 * placed / n) if n else 0,
        kinds=kinds, top_species=top_species, matched=matched, care=care, rep_kinds=rep_kinds,
        rep_open=sum(1 for r in rep if not r[1]), rep_total=len(rep), cat_habit=cat_habit, cat_use=cat_use,
        cat_total=db.execute("SELECT COUNT(*) FROM species").fetchone()[0],
        cat_report=db.execute("SELECT COUNT(*) FROM species WHERE basis='R'").fetchone()[0])

init_db()
if __name__ == "__main__":
    print("Running at http://localhost:5000   (admin password: set ADMIN_PASSWORD env var; default is admin123)")
    app.run(host="0.0.0.0", port=5000, debug=False)