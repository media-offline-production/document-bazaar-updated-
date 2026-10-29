import os
import sqlite3
import hashlib
import hmac
import secrets
import shutil
from decimal import Decimal
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "document_bazaar.db"
UPLOAD_FOLDER = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "xls", "xlsx", "zip"}

# Built-in paid resources included with the starter project. Seeded idempotently.
SEED_DOCUMENTS = [
    {
        "title": "Interview Assessment Form",
        "description": "A ready-to-use interview assessment form for use across industries. Copy it, adapt the company name, and assess candidates consistently. Includes candidate and role details, functional competencies, achievements and weaknesses, behavioural attributes, hiring recommendation, and interviewer details.",
        "category": "Templates", "price_paise": 1500,
        "source": "Interview Assessment Form.docx",
        "filename": "starter_interview_assessment_form.docx",
    },
    {
        "title": "HR Interview Questions PPT",
        "description": "An editable presentation with 50 common HR interview questions and sample answers, including tell me about yourself, salary expectations, strengths and weaknesses, and why should we hire you. Designed for freshers and candidates preparing for BPO, medical billing, and IT interviews.",
        "category": "Career", "price_paise": 3500,
        "source": "HR INTEVIEW QUESTIONS.pptx",
        "filename": "starter_hr_interview_questions.pptx",
    },
    {
        "title": "Church Management Skills",
        "description": "A descriptive manual by Samuel Jose, Senior Pastor at Holy Trinity Church, Cochin, India, intended for newcomers to the work of God across denominations. Covers soul winning, counselling, offerings, Sunday school, people management, teamwork, communication, assertiveness, goal setting, conflict management, time management, and cultural balance.",
        "category": "Study Notes", "price_paise": 12000,
        "source": "Church Management Skills.docx",
        "filename": "starter_church_management_skills.docx",
    },
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("DOCUMENT_BAZAAR_SECRET", "change-this-dev-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

DATABASE.parent.mkdir(exist_ok=True)
UPLOAD_FOLDER.mkdir(exist_ok=True)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'customer',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'Other',
            price_paise INTEGER NOT NULL DEFAULT 0,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            uploader_id INTEGER NOT NULL,
            is_approved INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(uploader_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, document_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(document_id) REFERENCES documents(id)
        );
        CREATE TABLE IF NOT EXISTS payment_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txnid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            amount_paise INTEGER NOT NULL,
            platform_fee_paise INTEGER NOT NULL,
            creator_share_paise INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            payu_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(document_id) REFERENCES documents(id)
        );
        """)
        # Create a local lead account for testing only. Change credentials before real deployment.
        lead_email = os.environ.get("DOCUMENT_BAZAAR_LEAD_EMAIL", "lead@documentbazaar.local")
        lead_password = os.environ.get("DOCUMENT_BAZAAR_LEAD_PASSWORD", "LeadDemo123!")
        exists = db.execute("SELECT id FROM users WHERE email = ?", (lead_email,)).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'lead')",
                ("Document Bazaar Lead", lead_email, generate_password_hash(lead_password))
            )

        # Copy and register the built-in products once. Files are bundled under seed_documents/.
        lead = db.execute("SELECT id FROM users WHERE email = ?", (lead_email,)).fetchone()
        if lead:
            seed_folder = BASE_DIR / "seed_documents"
            for item in SEED_DOCUMENTS:
                target = UPLOAD_FOLDER / item["filename"]
                source = seed_folder / item["source"]
                if source.exists() and not target.exists():
                    shutil.copy2(source, target)
                exists = db.execute(
                    "SELECT id FROM documents WHERE filename = ? OR title = ?",
                    (item["filename"], item["title"])
                ).fetchone()
                if target.exists():
                    if exists:
                        # Keep the bundled products paid and published on existing databases too.
                        db.execute(
                            """UPDATE documents SET title=?, description=?, category=?, price_paise=?,
                               filename=?, original_filename=?, uploader_id=?, is_approved=1 WHERE id=?""",
                            (item["title"], item["description"], item["category"], item["price_paise"],
                             item["filename"], item["source"], lead["id"], exists["id"])
                        )
                    else:
                        db.execute(
                            """INSERT INTO documents
                               (title, description, category, price_paise, filename, original_filename, uploader_id, is_approved)
                               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                            (item["title"], item["description"], item["category"], item["price_paise"],
                             item["filename"], item["source"], lead["id"])
                        )


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_db() as db:
        row = db.execute("SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

@app.context_processor
def inject_user():
    return {"user": current_user()}

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please sign in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

def lead_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        person = current_user()
        if not person:
            flash("Please sign in with the lead account.", "info")
            return redirect(url_for("login", next=request.path))
        if person["role"] != "lead":
            abort(403)
        return view(*args, **kwargs)
    return wrapped

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    with get_db() as db:
        sql = """SELECT d.*, u.name AS uploader_name FROM documents d
                 JOIN users u ON u.id = d.uploader_id
                 WHERE d.is_approved = 1 AND d.price_paise > 0"""
        params = []
        if search:
            sql += " AND (d.title LIKE ? OR d.description LIKE ? OR d.category LIKE ?)"
            term = f"%{search}%"
            params.extend([term, term, term])
        if category:
            sql += " AND d.category = ?"
            params.append(category)
        sql += " ORDER BY d.created_at DESC"
        documents = [dict(row) for row in db.execute(sql, params).fetchall()]
        categories = [r["category"] for r in db.execute(
            "SELECT DISTINCT category FROM documents WHERE is_approved = 1 AND price_paise > 0 ORDER BY category"
        ).fetchall()]
    return render_template("index.html", documents=documents, categories=categories, search=search, selected_category=category)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password of at least 8 characters.", "error")
            return render_template("auth.html", mode="register")
        try:
            with get_db() as db:
                db.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password))
                )
            flash("Account created! You can now sign in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email is already registered. Please sign in instead.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with get_db() as db:
            person = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if person and check_password_hash(person["password_hash"], password):
            session.clear()
            session["user_id"] = person["id"]
            flash(f"Welcome back, {person['name']}!", "success")
            next_url = request.args.get("next", "")
            if person["role"] == "lead":
                return redirect(url_for("lead_dashboard"))
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("index"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "Other").strip() or "Other"
        try:
            price_rupees = float(request.form.get("price", "0"))
            price_paise = int(round(price_rupees * 100))
        except ValueError:
            price_paise = -1
        upload = request.files.get("document")
        if not title or price_paise <= 0 or not upload or not upload.filename:
            flash("Add a title, a price greater than ₹0, and a file.", "error")
            return render_template("sell.html")
        if not allowed_file(upload.filename):
            flash("Unsupported file type. Please upload PDF, Office, TXT, or ZIP files.", "error")
            return render_template("sell.html")
        original = secure_filename(upload.filename)
        safe_name = f"user{current_user()['id']}_{os.urandom(8).hex()}_{original}"
        upload.save(UPLOAD_FOLDER / safe_name)
        with get_db() as db:
            db.execute(
                """INSERT INTO documents
                   (title, description, category, price_paise, filename, original_filename, uploader_id, is_approved)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (title, description, category, price_paise, safe_name, original, current_user()["id"])
            )
        flash("Upload submitted for lead review. It will appear in the marketplace after approval.", "success")
        return redirect(url_for("my_library"))
    return render_template("sell.html")

@app.route("/library")
@login_required
def my_library():
    person = current_user()
    with get_db() as db:
        rows = db.execute(
            """SELECT d.*, p.purchased_at FROM purchases p
               JOIN documents d ON d.id = p.document_id
               WHERE p.user_id = ? ORDER BY p.purchased_at DESC""",
            (person["id"],)
        ).fetchall()
    return render_template("library.html", purchases=[dict(row) for row in rows])

@app.route("/lead")
@lead_required
def lead_dashboard():
    with get_db() as db:
        pending = [dict(r) for r in db.execute(
            """SELECT d.*, u.name AS uploader_name, u.email AS uploader_email
               FROM documents d JOIN users u ON u.id=d.uploader_id
               WHERE d.is_approved=0 ORDER BY d.created_at DESC"""
        ).fetchall()]
        approved = [dict(r) for r in db.execute(
            """SELECT d.*, u.name AS uploader_name FROM documents d
               JOIN users u ON u.id=d.uploader_id
               WHERE d.is_approved=1 ORDER BY d.created_at DESC"""
        ).fetchall()]
        stats = {
            "users": db.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0],
            "pending": len(pending),
            "approved": len(approved),
            "purchases": db.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
        }
    return render_template("lead.html", pending=pending, approved=approved, stats=stats)

@app.route("/lead/documents/<int:document_id>/approve", methods=["POST"])
@lead_required
def approve_document(document_id):
    with get_db() as db:
        cur = db.execute("UPDATE documents SET is_approved=1 WHERE id=?", (document_id,))
        if cur.rowcount == 0:
            abort(404)
    flash("Document approved and published.", "success")
    return redirect(url_for("lead_dashboard"))

@app.route("/lead/documents/<int:document_id>/reject", methods=["POST"])
@lead_required
def reject_document(document_id):
    with get_db() as db:
        row = db.execute("SELECT filename FROM documents WHERE id=? AND is_approved=0", (document_id,)).fetchone()
        if not row:
            abort(404)
        db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    try:
        (UPLOAD_FOLDER / row["filename"]).unlink(missing_ok=True)
    except OSError:
        pass
    flash("Pending submission rejected and removed.", "info")
    return redirect(url_for("lead_dashboard"))

def payu_configured():
    return bool(os.environ.get("PAYU_MERCHANT_KEY") and os.environ.get("PAYU_MERCHANT_SALT"))

def payu_mode():
    # Intentionally test-only. Production checkout is blocked in this starter.
    return os.environ.get("PAYU_MODE", "test").strip().lower()

def amount_rupees(paise):
    return f"{Decimal(paise) / Decimal(100):.2f}"

def payu_request_hash(params, salt):
    # PayU hosted checkout request hash: key|txnid|amount|productinfo|firstname|email|udf1..udf5|salt
    fields = [params.get("key", ""), params.get("txnid", ""), params.get("amount", ""),
              params.get("productinfo", ""), params.get("firstname", ""), params.get("email", ""),
              params.get("udf1", ""), params.get("udf2", ""), params.get("udf3", ""),
              params.get("udf4", ""), params.get("udf5", ""), salt]
    return hashlib.sha512("|".join(fields).encode("utf-8")).hexdigest()

def payu_response_hash(form, salt):
    # PayU reverse hash for standard hosted checkout response, including additionalCharges when present.
    seq = []
    if form.get("additionalCharges"):
        seq.append(form.get("additionalCharges", ""))
    seq.append(salt)
    seq.extend([form.get("status", ""), "", "", "", "", "",
                form.get("udf5", ""), form.get("udf4", ""), form.get("udf3", ""),
                form.get("udf2", ""), form.get("udf1", ""), form.get("email", ""),
                form.get("firstname", ""), form.get("productinfo", ""), form.get("amount", ""),
                form.get("txnid", ""), form.get("key", "")])
    return hashlib.sha512("|".join(seq).encode("utf-8")).hexdigest()

@app.route("/document/<int:document_id>")
def document_detail(document_id):
    with get_db() as db:
        row = db.execute(
            """SELECT d.*, u.name AS uploader_name FROM documents d
               JOIN users u ON u.id = d.uploader_id
               WHERE d.id = ? AND d.is_approved = 1 AND d.price_paise > 0""",
            (document_id,)
        ).fetchone()
    if not row:
        abort(404)
    doc = dict(row)
    person = current_user()
    already_owned = False
    if person:
        with get_db() as db:
            already_owned = bool(db.execute(
                "SELECT 1 FROM purchases WHERE user_id=? AND document_id=?",
                (person["id"], document_id)
            ).fetchone())
    return render_template("document_detail.html", doc=doc, already_owned=already_owned)


@app.route("/document/<int:document_id>/purchase", methods=["POST"])
@login_required
def purchase_document(document_id):
    person = current_user()
    with get_db() as db:
        doc = db.execute("SELECT * FROM documents WHERE id=? AND is_approved=1", (document_id,)).fetchone()
        if not doc:
            abort(404)
        if doc["uploader_id"] == person["id"]:
            flash("You cannot purchase your own upload.", "error")
            return redirect(url_for("index"))
        existing = db.execute("SELECT 1 FROM purchases WHERE user_id=? AND document_id=?", (person["id"], document_id)).fetchone()
        if existing:
            flash("This document is already in your library.", "info")
            return redirect(url_for("my_library"))
        if int(doc["price_paise"]) <= 0:
            flash("This marketplace only supports paid resources. Please contact the lead about this listing.", "error")
            return redirect(url_for("index"))
        if not payu_configured():
            flash("PayU test checkout is not configured yet. No payment was collected. Add your TEST merchant key and salt as environment variables after obtaining them from PayU.", "info")
            return redirect(url_for("index"))
        if payu_mode() != "test":
            flash("Live payments are disabled in this starter until PayU Split Settlements and production configuration are verified.", "error")
            return redirect(url_for("index"))
        amount = int(doc["price_paise"])
        platform_fee = (amount * 30 + 50) // 100
        creator_share = amount - platform_fee
        txnid = "DB" + secrets.token_hex(10)
        db.execute("INSERT INTO payment_orders (txnid,user_id,document_id,amount_paise,platform_fee_paise,creator_share_paise,status) VALUES (?,?,?,?,?,?, 'pending')",
                   (txnid, person["id"], document_id, amount, platform_fee, creator_share))
    return redirect(url_for("payu_checkout", txnid=txnid))

@app.route("/payment/payu/<txnid>")
@login_required
def payu_checkout(txnid):
    if not payu_configured() or payu_mode() != "test":
        abort(503)
    person = current_user()
    with get_db() as db:
        order = db.execute("SELECT o.*, d.title FROM payment_orders o JOIN documents d ON d.id=o.document_id WHERE o.txnid=? AND o.user_id=?", (txnid, person["id"])).fetchone()
    if not order or order["status"] != "pending":
        abort(404)
    key = os.environ["PAYU_MERCHANT_KEY"]
    salt = os.environ["PAYU_MERCHANT_SALT"]
    params = {
        "key": key, "txnid": order["txnid"], "amount": amount_rupees(order["amount_paise"]),
        "productinfo": order["title"][:100], "firstname": person["name"][:60], "email": person["email"],
        "phone": os.environ.get("PAYU_TEST_PHONE", "9999999999"),
        "surl": url_for("payu_callback", _external=True), "furl": url_for("payu_callback", _external=True),
        "udf1": str(order["id"]), "udf2": str(order["document_id"]), "udf3": "", "udf4": "", "udf5": ""
    }
    params["hash"] = payu_request_hash(params, salt)
    return render_template("payu_checkout.html", params=params, endpoint="https://test.payu.in/_payment")

@app.route("/payment/payu/callback", methods=["POST"])
def payu_callback():
    if not payu_configured() or payu_mode() != "test":
        abort(503)
    form = request.form.to_dict(flat=True)
    expected = payu_response_hash(form, os.environ["PAYU_MERCHANT_SALT"])
    received = form.get("hash", "")
    if not received or not hmac.compare_digest(expected.lower(), received.lower()):
        flash("PayU response could not be verified. No download has been unlocked.", "error")
        return redirect(url_for("index"))
    txnid = form.get("txnid", "")
    with get_db() as db:
        order = db.execute("SELECT * FROM payment_orders WHERE txnid=?", (txnid,)).fetchone()
        if not order:
            abort(404)
        if form.get("key") != os.environ["PAYU_MERCHANT_KEY"] or form.get("amount") != amount_rupees(order["amount_paise"]):
            abort(400)
        if form.get("status", "").lower() == "success":
            db.execute("UPDATE payment_orders SET status='paid', payu_id=?, updated_at=CURRENT_TIMESTAMP WHERE txnid=? AND status='pending'",
                       (form.get("mihpayid"), txnid))
            db.execute("INSERT OR IGNORE INTO purchases (user_id, document_id) VALUES (?, ?)", (order["user_id"], order["document_id"]))
            flash("Test payment verified. The document is now in your library. No live funds were collected.", "success")
        else:
            db.execute("UPDATE payment_orders SET status='failed', payu_id=?, updated_at=CURRENT_TIMESTAMP WHERE txnid=? AND status='pending'",
                       (form.get("mihpayid"), txnid))
            flash("Payment was not completed. The document has not been unlocked.", "error")
        user_id = order["user_id"]
    session["user_id"] = user_id
    return redirect(url_for("my_library"))

@app.route("/download/<int:document_id>")
@login_required
def download_document(document_id):
    from flask import send_from_directory
    person = current_user()
    with get_db() as db:
        purchased = db.execute(
            "SELECT 1 FROM purchases WHERE user_id=? AND document_id=?",
            (person["id"], document_id)
        ).fetchone()
        if person["role"] == "lead":
            purchased = True
        doc = db.execute("SELECT * FROM documents WHERE id=? AND is_approved=1", (document_id,)).fetchone()
    if not doc:
        abort(404)
    if not purchased and doc["uploader_id"] != person["id"]:
        abort(403)
    return send_from_directory(UPLOAD_FOLDER, doc["filename"], as_attachment=True, download_name=doc["original_filename"])

@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You don't have permission to view this page."), 403

@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404

@app.errorhandler(413)
def too_large(_error):
    flash("The upload is too large. Maximum file size is 25 MB.", "error")
    return redirect(url_for("sell"))

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True)
