from flask_socketio import SocketIO, emit, join_room
from email.message import EmailMessage
import os
import socket
import smtplib
import ssl
import uuid
import re
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, request, redirect, session, flash, abort, url_for
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chatti.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", "587"))
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "false").lower() == "true"

db = SQLAlchemy(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

MAX_MESSAGE_LEN = 2000
MAX_PROFILE_IMAGE_BYTES = 3 * 1024 * 1024
MAX_STATUS_MEDIA_BYTES = 25 * 1024 * 1024
RESET_TOKEN_MAX_AGE = 60 * 60

# ======================
# ONLINE USERS
# ======================
# Each user can have several browser tabs/devices connected at once.
online_sessions = {}
chat_room_viewers = {}
expiry_cleanup_started = False


def online_user_ids():
    return {uid for uid, sids in online_sessions.items() if sids}


def utcnow():
    """Naive UTC timestamp, without datetime.utcnow()'s 3.12 deprecation."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def message_expiry(retention, sent_at):
    durations = {"12h": timedelta(hours=12), "24h": timedelta(hours=24), "30d": timedelta(days=30)}
    duration = durations.get(retention or "off")
    return sent_at + duration if duration else None


def activity_label(user, online=False):
    if online:
        return "Online"
    if not user or not user.last_active_at:
        return "Offline"
    seconds = max(0, int((utcnow() - user.last_active_at).total_seconds()))
    if seconds < 60:
        return "Just left"
    minutes = seconds // 60
    if minutes < 60:
        return f"Left {minutes} min{'s' if minutes != 1 else ''} ago"
    hours = seconds // 3600
    if hours < 24:
        return f"Active {hours}h ago"
    days = seconds // 86400
    if days < 14:
        return f"Active {days}d ago"
    weeks = days // 7
    return f"Active {weeks} weeks ago"


# ======================
# MODELS
# ======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)

    avatar_url = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.String(120), nullable=True)
    message_retention = db.Column(db.String(20), nullable=True, default="off")
    last_active_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=True)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=utcnow)
    edited_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    delete_after_seen = db.Column(db.Boolean, nullable=True, default=False)


class Status(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    media_url = db.Column(db.String(255), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)
    timestamp = db.Column(db.DateTime, default=utcnow)


# ======================
# HELPERS
# ======================
def ensure_schema():
    """Bring an existing database up to date with the models.

    `db.create_all()` only creates missing *tables* -- it never adds columns to
    a table that already exists. So an older chatti.db keeps its old shape and
    every query dies with "no such column: user.<field>". Fill in the missing
    columns here, then create any tables that were absent altogether.

    Returns the list of "<table>.<column>" names it had to add.
    """
    db.create_all()

    inspector = inspect(db.engine)
    dialect = db.engine.dialect
    added = []

    for model in db.Model.__subclasses__():
        table = model.__tablename__

        if table not in inspector.get_table_names():
            continue

        existing = {c["name"] for c in inspector.get_columns(table)}

        for column in model.__table__.columns:
            if column.name in existing:
                continue

            # SQLite can only ADD COLUMN if it is nullable or has a constant
            # default. Every column we add here is nullable, so this is safe.
            col_type = column.type.compile(dialect=dialect)

            db.session.execute(
                text(f'ALTER TABLE "{table}" ADD COLUMN "{column.name}" {col_type}')
            )
            added.append(f"{table}.{column.name}")

    db.session.commit()
    return added


def get_friends(uid):
    accepted = Friendship.query.filter(
        ((Friendship.user_id == uid) | (Friendship.friend_id == uid)) &
        (Friendship.status.is_(None) | (Friendship.status == "accepted"))
    ).all()
    return [row.friend_id if row.user_id == uid else row.user_id for row in accepted]


def are_friends(a, b):
    if a is None or b is None or a == b:
        return False

    return Friendship.query.filter(
        (((Friendship.user_id == a) & (Friendship.friend_id == b)) |
         ((Friendship.user_id == b) & (Friendship.friend_id == a))) &
        (Friendship.status.is_(None) | (Friendship.status == "accepted"))
    ).first() is not None


def room(a, b):
    return f"chat_{min(a, b)}_{max(a, b)}"


def socket_user():
    """The logged-in user id for the current socket, or None."""
    return session.get("user_id")


def peer_id(data):
    """The `friend_id` from a client payload, as an int, or None if bogus."""
    try:
        return int(data.get("friend_id"))
    except (TypeError, ValueError, AttributeError):
        return None


def valid_peer(data):
    """(uid, fid) if this socket may talk to `friend_id`, else (None, None)."""
    uid = socket_user()
    fid = peer_id(data)

    if uid is None or not are_friends(uid, fid):
        return None, None

    return uid, fid


def valid_email(value):
    return bool(value and len(value) <= 254 and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def valid_new_password(value):
    return value.isascii() and value.isalnum() and len(value) in (6, 8)


def reset_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="chatti-password-reset")


def send_password_reset_email(user, token):
    mail_server = app.config["MAIL_SERVER"]
    sender = app.config["MAIL_DEFAULT_SENDER"] or app.config["MAIL_USERNAME"]
    if not mail_server or not sender:
        app.logger.warning("Password reset requested but SMTP is not configured")
        return False
    if not app.config["SECRET_KEY"] or app.config["SECRET_KEY"] == "dev":
        app.logger.error("Password reset email blocked because SECRET_KEY is not configured securely")
        return False

    public_base_url = os.environ.get("APP_BASE_URL")
    if not public_base_url:
        app.logger.warning("Password reset requested but APP_BASE_URL is not configured")
        return False
    base_url = public_base_url.rstrip("/")
    reset_url = f"{base_url}{url_for('reset_password', token=token)}"
    message = EmailMessage()
    message["Subject"] = "Reset your CHATTI password"
    message["From"] = sender
    message["To"] = user.email
    message.set_content(
        "We received a request to reset your CHATTI password.\n\n"
        f"Use this link within one hour: {reset_url}\n\n"
        "If you did not request a password reset, you can ignore this email."
    )

    try:
        if app.config["MAIL_USE_SSL"]:
            with smtplib.SMTP_SSL(
                mail_server, app.config["MAIL_PORT"], timeout=10,
                context=ssl.create_default_context()
            ) as server:
                if app.config["MAIL_USERNAME"]:
                    server.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"] or "")
                server.send_message(message)
        else:
            with smtplib.SMTP(mail_server, app.config["MAIL_PORT"], timeout=10) as server:
                if app.config["MAIL_USE_TLS"]:
                    server.starttls(context=ssl.create_default_context())
                if app.config["MAIL_USERNAME"]:
                    server.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"] or "")
                server.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.exception("Unable to send a CHATTI password reset email")
        return False
    return True


# ======================
# ROUTES
# ======================
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/friends")
    return redirect("/login")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not username or not email or not password:
            flash("Username, email, and password are required", "error")
            return redirect("/signup")

        if not valid_email(email):
            flash("Enter a valid email address", "error")
            return redirect("/signup")

        if not valid_new_password(password):
            flash("Password must be exactly 6 or 8 letters or numbers, with no spaces or symbols", "error")
            return redirect("/signup")

        if User.query.filter_by(username=username).first():
            flash("User exists", "error")
            return redirect("/signup")

        if User.query.filter_by(email=email).first():
            flash("An account already uses that email address", "error")
            return redirect("/signup")

        db.session.add(User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            avatar_url=None,   # default
            bio=""
        ))
        db.session.commit()

        return redirect("/login")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(
            username=(request.form.get("username") or "").strip()
        ).first()

        if user and check_password_hash(user.password, request.form.get("password") or ""):
            session["user_id"] = user.id
            session.permanent = request.form.get("remember_me") == "on"
            return redirect("/friends")

        flash("Invalid login", "error")
        return redirect("/login")

    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = User.query.filter_by(email=email).first() if valid_email(email) else None
        if user:
            token = reset_serializer().dumps({
                "user_id": user.id, "email": user.email,
                "password_hash": user.password,
            })
            send_password_reset_email(user, token)

        # Keep the response the same for known and unknown email addresses.
        flash(
            "If an account uses that email address, a reset link will be sent. "
            "The link expires after one hour.",
            "success",
        )
        return redirect("/forgot-password")

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        payload = reset_serializer().loads(token, max_age=RESET_TOKEN_MAX_AGE)
    except SignatureExpired:
        flash("That reset link has expired. Request a new one.", "error")
        return redirect("/forgot-password")
    except BadSignature:
        flash("That reset link is invalid. Request a new one.", "error")
        return redirect("/forgot-password")

    if not isinstance(payload, dict):
        flash("That reset link is no longer valid. Request a new one.", "error")
        return redirect("/forgot-password")

    user = db.session.get(User, payload.get("user_id"))
    if (
        not user or user.email != payload.get("email")
        or user.password != payload.get("password_hash")
    ):
        flash("That reset link is no longer valid. Request a new one.", "error")
        return redirect("/forgot-password")

    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        if not valid_new_password(password):
            flash("Password must be exactly 6 or 8 letters or numbers, with no spaces or symbols", "error")
        elif password != confirm_password:
            flash("The passwords do not match", "error")
        else:
            user.password = generate_password_hash(password)
            db.session.commit()
            flash("Password reset. You can now log in.", "success")
            return redirect("/login")

    return render_template("reset_password.html", token=token)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/friends")
def friends():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    ids = get_friends(uid)

    friends = User.query.filter(User.id.in_(ids)).all() if ids else []
    accounts = User.query.filter(User.id != uid).order_by(User.username).all()
    incoming_adds = Friendship.query.filter_by(friend_id=uid, status="pending").all()
    incoming_ids = [row.user_id for row in incoming_adds]
    incoming_people = User.query.filter(User.id.in_(incoming_ids)).all() if incoming_ids else []
    incoming_requests = [
        {"id": row.id, "person": person}
        for row in incoming_adds
        for person in incoming_people
        if person.id == row.user_id
    ]
    outgoing_ids = {
        row.friend_id for row in Friendship.query.filter_by(user_id=uid, status="pending").all()
    }
    incoming_request_by_user = {row.user_id: row.id for row in incoming_adds}

    return render_template(
        "friends.html",
        friends=friends,
        accounts=accounts,
        friend_ids=set(ids),
        incoming_requests=incoming_requests,
        incoming_request_by_user=incoming_request_by_user,
        outgoing_ids=outgoing_ids,
        online_users=online_user_ids()
    )


@app.route("/add_friend", methods=["POST"])
def add_friend():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    username = (request.form.get("username") or "").strip()

    if not username:
        flash("Enter a username", "error")
        return redirect("/friends")

    other = User.query.filter_by(username=username).first()
    existing = None
    if other is not None and other.id != uid:
        existing = Friendship.query.filter(
            ((Friendship.user_id == uid) & (Friendship.friend_id == other.id)) |
            ((Friendship.user_id == other.id) & (Friendship.friend_id == uid))
        ).first()

    if other is None:
        flash("No user with that name", "error")
    elif other.id == uid:
        flash("You cannot add yourself", "error")
    elif are_friends(uid, other.id):
        flash(f"{other.username} is already a friend", "error")
    elif existing and existing.status == "pending":
        if existing.user_id == uid:
            flash(f"Friend request already sent to {other.username}", "error")
        else:
            flash(f"{other.username} already sent you a request. Accept it on this page.", "error")
    else:
        db.session.add(Friendship(user_id=uid, friend_id=other.id, status="pending"))
        db.session.commit()
        flash(f"Friend request sent to {other.username}", "success")

    return redirect("/friends")


@app.route("/friend_request/<int:request_id>/<action>", methods=["POST"])
def respond_friend_request(request_id, action):
    if "user_id" not in session:
        return redirect("/login")
    if action not in {"accept", "decline"}:
        abort(404)

    friend_request = Friendship.query.filter_by(
        id=request_id, friend_id=session["user_id"], status="pending"
    ).first_or_404()
    requester = db.session.get(User, friend_request.user_id)
    if action == "accept":
        friend_request.status = "accepted"
        flash(f"You and {requester.username} are now friends", "success")
    else:
        db.session.delete(friend_request)
        flash("Friend request declined", "success")
    db.session.commit()
    return redirect("/friends")


@app.route("/remove_friend/<int:fid>", methods=["POST"])
def remove_friend(fid):
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    rows = Friendship.query.filter(
        ((Friendship.user_id == uid) & (Friendship.friend_id == fid)) |
        ((Friendship.user_id == fid) & (Friendship.friend_id == uid))
    ).all()
    if rows:
        for row in rows:
            db.session.delete(row)
        db.session.commit()
        flash("Friend removed", "success")
    return redirect("/friends")


@app.route("/status", methods=["GET", "POST"])
def status_page():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    if request.method == "POST":
        content = (request.form.get("content") or "").strip()
        media_file = request.files.get("media_file")
        media_bytes = media_file.read(MAX_STATUS_MEDIA_BYTES + 1) if media_file and media_file.filename else None
        media_mime = media_file.mimetype if media_file else ""
        signatures = {
            "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
            "image/gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
            "image/webp": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
            "video/mp4": lambda data: len(data) >= 12 and data[4:8] == b"ftyp",
            "video/webm": lambda data: data.startswith(b"\x1a\x45\xdf\xa3"),
            "audio/mp4": lambda data: len(data) >= 12 and data[4:8] == b"ftyp",
            "audio/webm": lambda data: data.startswith(b"\x1a\x45\xdf\xa3"),
            "audio/mpeg": lambda data: data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0),
            "audio/ogg": lambda data: data.startswith(b"OggS"),
            "audio/wav": lambda data: len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE",
            "audio/x-wav": lambda data: len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE",
        }
        media_valid = not media_bytes or (
            media_mime in signatures and signatures[media_mime](media_bytes)
        )

        if media_bytes and len(media_bytes) > MAX_STATUS_MEDIA_BYTES:
            flash("Choose a photo, video, or audio file smaller than 25 MB", "error")
        elif media_bytes and not media_valid:
            flash("Choose a JPG, PNG, GIF, WebP, MP4, WebM, MP3, M4A, OGG, or WAV file", "error")
        elif not content and not media_bytes:
            flash("Write an update or add a photo, video, or audio file", "error")
        elif len(content) > 500:
            flash("Update must be 500 characters or fewer", "error")
        else:
            media_url = None
            media_type = None
            if media_bytes:
                extension = {
                    "image/png": "png", "image/jpeg": "jpg",
                    "image/gif": "gif", "image/webp": "webp",
                    "video/mp4": "mp4", "video/webm": "webm",
                    "audio/mp4": "m4a", "audio/webm": "webm",
                    "audio/mpeg": "mp3", "audio/ogg": "ogg",
                    "audio/wav": "wav", "audio/x-wav": "wav",
                }[media_mime]
                upload_dir = os.path.join(app.static_folder, "uploads", "status")
                os.makedirs(upload_dir, exist_ok=True)
                filename = f"{uuid.uuid4().hex}.{extension}"
                with open(os.path.join(upload_dir, filename), "wb") as uploaded_file:
                    uploaded_file.write(media_bytes)
                media_url = f"/static/uploads/status/{filename}"
                media_type = media_mime.split("/", 1)[0]

            db.session.add(Status(
                user_id=uid, content=content,
                media_url=media_url, media_type=media_type
            ))
            db.session.commit()
            flash("Update shared", "success")
            return redirect("/status")

    friend_ids = get_friends(uid)
    visible_ids = friend_ids + [uid]
    cutoff = utcnow() - timedelta(hours=12)
    statuses = db.session.query(Status, User).join(User, User.id == Status.user_id).filter(
        Status.user_id.in_(visible_ids), Status.timestamp >= cutoff
    ).order_by(Status.timestamp.desc()).all() if visible_ids else []
    own_statuses = [(status, author) for status, author in statuses if author.id == uid]
    friend_statuses = [(status, author) for status, author in statuses if author.id != uid]
    return render_template(
        "status.html", own_statuses=own_statuses,
        friend_statuses=friend_statuses, current_user_id=uid,
        current_user=db.session.get(User, uid)
    )


@app.route("/status/<int:status_id>/delete", methods=["POST"])
def delete_status(status_id):
    if "user_id" not in session:
        return redirect("/login")

    status = db.session.get(Status, status_id)
    if status and status.user_id == session["user_id"]:
        db.session.delete(status)
        db.session.commit()
        flash("Update deleted", "success")
    return redirect("/status")


@app.route("/profile", methods=["GET", "POST"])
@app.route("/profile/<int:user_id>", methods=["GET", "POST"])
def profile(user_id=None):
    if "user_id" not in session:
        return redirect("/login")

    current_id = session["user_id"]
    is_owner = user_id is None or user_id == current_id
    target_id = current_id if user_id is None else user_id
    user = db.session.get(User, target_id)
    if user is None:
        abort(404)
    if not is_owner and not are_friends(current_id, target_id):
        abort(403)
    if request.method == "POST" and not is_owner:
        abort(403)

    if request.method == "POST":
        bio = (request.form.get("bio") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        remove_picture = request.form.get("remove_picture") == "on"
        image = request.files.get("profile_picture")
        image_bytes = image.read(MAX_PROFILE_IMAGE_BYTES + 1) if image and image.filename else None

        if image_bytes and len(image_bytes) > MAX_PROFILE_IMAGE_BYTES:
            flash("Choose an image smaller than 3 MB", "error")
        elif image_bytes and not (
            (image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and image.mimetype == "image/png")
            or (image_bytes.startswith(b"\xff\xd8\xff") and image.mimetype == "image/jpeg")
            or (image_bytes.startswith((b"GIF87a", b"GIF89a")) and image.mimetype == "image/gif")
            or (image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP" and image.mimetype == "image/webp")
        ):
            flash("Choose a valid PNG, JPG, GIF, or WebP image", "error")
        elif email and not valid_email(email):
            flash("Enter a valid recovery email address", "error")
        elif email and User.query.filter(User.email == email, User.id != user.id).first():
            flash("That email address is already used by another account", "error")
        elif len(bio) > 120:
            flash("Your bio must be 120 characters or fewer", "error")
        else:
            if image_bytes:
                extension = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}[image.mimetype]
                upload_dir = os.path.join(app.static_folder, "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                filename = f"{uuid.uuid4().hex}.{extension}"
                with open(os.path.join(upload_dir, filename), "wb") as uploaded_file:
                    uploaded_file.write(image_bytes)
                user.avatar_url = f"/static/uploads/{filename}"
            elif remove_picture:
                user.avatar_url = None
            user.email = email or None
            user.bio = bio
            db.session.commit()
            flash("Profile updated", "success")
            return redirect("/profile")

    return render_template(
        "profile.html", user=user, is_owner=is_owner,
        online_users=online_user_ids()
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])
    if request.method == "POST":
        retention = request.form.get("message_retention", "off")
        if retention not in {"seen", "12h", "24h", "30d", "off"}:
            flash("Choose a valid message retention option", "error")
        else:
            user.message_retention = retention
            db.session.commit()
            flash("Message retention setting saved. It applies to new messages you send.", "success")
            return redirect("/settings")

    return render_template("settings.html", user=user)


@app.route("/chat/<int:fid>")
def chat(fid):
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    friend = db.session.get(User, fid)

    if friend is None:
        abort(404)

    if not are_friends(uid, fid):
        flash("You are not friends with that user", "error")
        return redirect("/friends")

    conversation_filter = (
        ((Message.sender_id == uid) & (Message.receiver_id == fid)) |
        ((Message.sender_id == fid) & (Message.receiver_id == uid))
    )
    expired = Message.query.filter(
        conversation_filter, Message.expires_at.isnot(None), Message.expires_at <= utcnow()
    ).all()
    for message in expired:
        db.session.delete(message)
    if expired:
        db.session.commit()
    messages = Message.query.filter(conversation_filter).order_by(Message.id).all()

    ids = get_friends(uid)
    sidebar = User.query.filter(User.id.in_(ids)).all() if ids else []

    online_users = online_user_ids()
    return render_template(
        "chat.html",
        friend=friend,
        friends=sidebar,
        messages=messages,
        current_user_id=uid,
        online_users=online_users,
        friend_activity=activity_label(friend, friend.id in online_users),
    )


def expire_messages_loop():
    while True:
        socketio.sleep(30)
        with app.app_context():
            expired = Message.query.filter(
                Message.expires_at.isnot(None), Message.expires_at <= utcnow()
            ).all()
            for message in expired:
                socketio.emit(
                    "message_deleted",
                    {"id": message.id},
                    to=room(message.sender_id, message.receiver_id),
                )
                db.session.delete(message)
            if expired:
                db.session.commit()
            db.session.remove()


# ======================
# SOCKET EVENTS
# ======================
@socketio.on("connect")
def on_connect():
    global expiry_cleanup_started
    if not expiry_cleanup_started:
        expiry_cleanup_started = True
        socketio.start_background_task(expire_messages_loop)

    uid = socket_user()
    if uid:
        sessions = online_sessions.setdefault(uid, set())
        was_offline = not sessions
        sessions.add(request.sid)
        if was_offline:
            emit("user_status", {"user_id": uid, "status": "online"}, broadcast=True)


@socketio.on("disconnect")
def on_disconnect():
    uid = socket_user()
    if uid:
        for room_name, viewers in list(chat_room_viewers.items()):
            user_sids = viewers.get(uid)
            if user_sids:
                user_sids.discard(request.sid)
                if not user_sids:
                    viewers.pop(uid, None)
                if not viewers:
                    chat_room_viewers.pop(room_name, None)
        sessions = online_sessions.get(uid, set())
        sessions.discard(request.sid)
        if not sessions:
            online_sessions.pop(uid, None)
            last_active = utcnow()
            user = db.session.get(User, uid)
            if user:
                user.last_active_at = last_active
                db.session.commit()
            emit("user_status", {
                "user_id": uid,
                "status": "offline",
                "last_active_at": last_active.isoformat() + "Z",
            }, broadcast=True)


@socketio.on("join")
def on_join(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return

    # The room is derived server-side -- never trust a client-supplied name.
    room_name = room(uid, fid)
    join_room(room_name)
    viewers = chat_room_viewers.setdefault(room_name, {})
    viewers.setdefault(uid, set()).add(request.sid)

    unread = Message.query.filter_by(
        sender_id=fid, receiver_id=uid, read_at=None
    ).all()
    if unread:
        now = utcnow()
        seen_message_ids = []
        read_message_ids = []
        for message in unread:
            if message.delete_after_seen:
                seen_message_ids.append(message.id)
                db.session.delete(message)
            else:
                message.delivered_at = message.delivered_at or now
                message.read_at = now
                read_message_ids.append(message.id)
        db.session.commit()
        if read_message_ids:
            emit("receipt_update", {
                "message_ids": read_message_ids,
                "status": "seen",
            }, room=room_name)
        if seen_message_ids:
            emit("message_deleted", {"ids": seen_message_ids}, room=room_name)


@socketio.on("send_message")
def handle_send_message(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return

    content = (data.get("content") or "").strip()
    if not content:
        return

    # sender_id comes from the session, so a client cannot impersonate.
    sender = db.session.get(User, uid)
    retention = sender.message_retention if sender else "off"
    now = utcnow()
    recipient_is_viewing = bool(
        chat_room_viewers.get(room(uid, fid), {}).get(fid)
    )
    msg = Message(
        sender_id=uid,
        receiver_id=fid,
        content=content[:MAX_MESSAGE_LEN],
        timestamp=now,
        expires_at=message_expiry(retention, now),
        delete_after_seen=retention == "seen",
    )
    if recipient_is_viewing:
        msg.delivered_at = now
        msg.read_at = msg.delivered_at

    db.session.add(msg)
    db.session.commit()

    emit("receive_message", {
        "id": msg.id,
        "content": msg.content,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "time": msg.timestamp.strftime("%H:%M"),
        "receipt": "seen" if msg.read_at else ("delivered" if msg.delivered_at else "sent"),
        "expires_at": msg.expires_at.isoformat() if msg.expires_at else None,
    }, room=room(uid, fid))
    if recipient_is_viewing and retention == "seen":
        db.session.delete(msg)
        db.session.commit()
        emit("message_deleted", {"id": msg.id}, room=room(uid, fid))


@socketio.on("edit_message")
def handle_edit_message(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return
    try:
        message_id = int(data.get("message_id"))
    except (TypeError, ValueError):
        return

    msg = Message.query.filter_by(
        id=message_id, sender_id=uid, receiver_id=fid
    ).first()
    content = (data.get("content") or "").strip()
    if msg is None or not content:
        return

    content = content[:MAX_MESSAGE_LEN]
    if content == msg.content:
        return

    msg.content = content
    msg.edited_at = utcnow()
    db.session.commit()
    emit("message_updated", {
        "id": msg.id,
        "content": msg.content,
    }, room=room(uid, fid))


@socketio.on("delete_message")
def handle_delete_message(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return {"ok": False}
    try:
        message_id = int(data.get("message_id"))
    except (TypeError, ValueError):
        return {"ok": False}

    msg = Message.query.filter_by(id=message_id).filter(
        ((Message.sender_id == uid) & (Message.receiver_id == fid)) |
        ((Message.sender_id == fid) & (Message.receiver_id == uid))
    ).first()
    if msg is None:
        return {"ok": False}

    db.session.delete(msg)
    db.session.commit()
    emit("message_deleted", {"id": message_id}, room=room(uid, fid))
    return {"ok": True}


@socketio.on("forward_message")
def handle_forward_message(data):
    uid, source_friend_id = valid_peer(data)
    if uid is None:
        return {"ok": False}
    try:
        message_id = int(data.get("message_id"))
        target_id = int(data.get("target_id"))
    except (TypeError, ValueError):
        return {"ok": False}
    if not are_friends(uid, target_id):
        return {"ok": False}

    source = Message.query.filter_by(id=message_id).filter(
        ((Message.sender_id == uid) & (Message.receiver_id == source_friend_id)) |
        ((Message.sender_id == source_friend_id) & (Message.receiver_id == uid))
    ).first()
    if source is None:
        return {"ok": False}

    target_room = room(uid, target_id)
    target_is_viewing = bool(chat_room_viewers.get(target_room, {}).get(target_id))
    sender = db.session.get(User, uid)
    retention = sender.message_retention if sender else "off"
    now = utcnow()
    forwarded = Message(
        sender_id=uid,
        receiver_id=target_id,
        content=("↪ Forwarded: " + source.content)[:MAX_MESSAGE_LEN],
        timestamp=now,
        expires_at=message_expiry(retention, now),
        delete_after_seen=retention == "seen",
    )
    if target_is_viewing:
        forwarded.delivered_at = now
        forwarded.read_at = forwarded.delivered_at
    db.session.add(forwarded)
    db.session.commit()

    emit("receive_message", {
        "id": forwarded.id,
        "content": forwarded.content,
        "sender_id": uid,
        "receiver_id": target_id,
        "time": forwarded.timestamp.strftime("%H:%M"),
        "receipt": "seen" if forwarded.read_at else ("delivered" if forwarded.delivered_at else "sent"),
        "expires_at": forwarded.expires_at.isoformat() if forwarded.expires_at else None,
    }, room=target_room)
    if target_is_viewing and retention == "seen":
        forwarded_id = forwarded.id
        db.session.delete(forwarded)
        db.session.commit()
        emit("message_deleted", {"id": forwarded_id}, room=target_room)
    return {"ok": True}


@socketio.on("typing")
def on_typing(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return

    emit("typing", {"user": uid}, room=room(uid, fid), include_self=False)


@socketio.on("stop_typing")
def on_stop_typing(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return

    emit("stop_typing", {"user": uid}, room=room(uid, fid), include_self=False)


def pick_port(preferred=5000, tries=20):
    """`preferred`, or the first free port above it if it is already taken.

    Port 5000 is a popular squatter -- macOS AirPlay and, on Windows, any
    service that bound it first. Losing that race is not this app's fault, and
    the failure mode (`bind` dying with "access permissions" or "address
    already in use") is cryptic. Probing here turns it into a non-event.

    Deliberately no SO_REUSEADDR: on Windows that lets `bind` appear to succeed
    against a port another process holds exclusively, which is exactly the case
    we are trying to detect.
    """
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port

    return preferred


# ======================
# RUN SERVER
# ======================
# Run this at import time, not just under __main__: gunicorn and `flask run`
# only import the module, and without this they would serve an app whose
# tables (or columns) do not exist yet.
with app.app_context():
    _added = ensure_schema()
    if _added:
        print("Schema updated: " + ", ".join(_added))


if __name__ == "__main__":
    # PORT pins a specific port (containers, tunnels); otherwise take the first
    # free one at or above 5000 and say so when that is not 5000.
    if os.environ.get("PORT"):
        _port = int(os.environ["PORT"])
    else:
        # Resolve once, then hand the answer to the reloader's child through the
        # environment. Re-probing on every reload would walk the port upward:
        # the outgoing child still holds the old port for an instant, so the
        # fresh probe sees it as busy and takes the next one.
        _port = int(os.environ.get("_CHATTI_PORT") or pick_port())
        os.environ["_CHATTI_PORT"] = str(_port)

        if _port != 5000 and not os.environ.get("WERKZEUG_RUN_MAIN"):
            print(f"Port 5000 is busy -- starting on http://127.0.0.1:{_port} instead.")

    socketio.run(app, host="127.0.0.1", port=_port, debug=True)
