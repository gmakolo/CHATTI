from flask_socketio import SocketIO, emit, join_room
from email.message import EmailMessage
import os
import socket
import smtplib
import ssl
import uuid
import re
from datetime import date, datetime, timedelta, timezone

from flask import (
    Flask, render_template, request, redirect, session, flash, abort, url_for, jsonify, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, text, update
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
CHAT_THEMES = {
    "forest": {"label": "Violet and lavender", "bg": "#FFFFFF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
    "mint": {"label": "Lavender mist", "bg": "#F5F3FF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
    "ocean": {"label": "Electric violet", "bg": "#FFFFFF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
    "sky": {"label": "Soft lavender", "bg": "#FFFFFF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
    "lavender": {"label": "Lavender light", "bg": "#F5F3FF", "sent": "#7C3AED", "received": "#FFFFFF", "accent": "#7C3AED"},
    "rose": {"label": "Dusty mauve", "bg": "#FFFFFF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#8B5E83"},
    "peach": {"label": "Bright white", "bg": "#FFFFFF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
    "sunshine": {"label": "Soft violet", "bg": "#F5F3FF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
    "plum": {"label": "Violet mist", "bg": "#FFFFFF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
    "midnight": {"label": "Midnight violet", "bg": "#FFFFFF", "sent": "#7C3AED", "received": "#EDE9FE", "accent": "#7C3AED"},
}
STICKER_SEEDS = [
    ("Big laugh", "happy funny laugh lol", "😂", "Reactions"),
    ("Tears of joy", "funny laugh happy", "🤣", "Reactions"),
    ("Love you", "love heart affection", "🥰", "Love"),
    ("Heart eyes", "love crush cute", "😍", "Love"),
    ("Kiss", "love kiss greeting", "😘", "Love"),
    ("Crying", "sad cry tears", "😭", "Feelings"),
    ("Sad", "sad disappointed", "😢", "Feelings"),
    ("Happy", "happy smile yay", "😊", "Feelings"),
    ("Cool", "cool sunglasses awesome", "😎", "Reactions"),
    ("Thinking", "think unsure hmm", "🤔", "Reactions"),
    ("Hello", "hello hi greeting wave", "👋", "Greetings"),
    ("Good morning", "morning hello greeting", "🌞", "Greetings"),
    ("Thank you", "thanks gratitude please", "🙏", "Greetings"),
    ("Celebrate", "party celebration congrats", "🎉", "Celebrations"),
    ("Clap", "clapping bravo well done", "👏", "Celebrations"),
    ("Fire", "fire amazing hot", "🔥", "Reactions"),
    ("Butterfly", "cute nature chatti", "🦋", "Everyday"),
    ("Sending hugs", "hug comfort care", "🫂", "Everyday"),
    ("Please", "please hope fingers crossed", "🤞", "Everyday"),
    ("Good night", "night sleep moon", "🌙", "Greetings"),
]

# ======================
# ONLINE USERS
# ======================
# Each user can have several browser tabs/devices connected at once.
online_sessions = {}
chat_room_viewers = {}
expiry_cleanup_started = False


def online_user_ids():
    return {uid for uid, sids in online_sessions.items() if sids}


def visible_online_user_ids(viewer_id=None):
    online_ids = online_user_ids()
    users = User.query.filter(User.id.in_(online_ids)).all() if online_ids else []
    return {user.id for user in users
            if user.id == viewer_id or user.show_online_status is not False}


def utcnow():
    """Naive UTC timestamp, without datetime.utcnow()'s 3.12 deprecation."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def message_expiry(retention, sent_at):
    durations = {"12h": timedelta(hours=12), "24h": timedelta(hours=24), "30d": timedelta(days=30)}
    duration = durations.get(retention or "off")
    return sent_at + duration if duration else None


def activity_label(user, online=False):
    if online:
        return "Active now"
    if not user or not user.last_active_at:
        return "Offline"
    seconds = max(0, int((utcnow() - user.last_active_at).total_seconds()))
    if seconds < 60:
        return "Last active just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"Last active {minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = seconds // 3600
    if hours < 24:
        return f"Last active {hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    if days < 14:
        return f"Last active {days} day{'s' if days != 1 else ''} ago"
    weeks = days // 7
    return f"Last active {weeks} week{'s' if weeks != 1 else ''} ago"


# ======================
# MODELS
# ======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)

    avatar_url = db.Column(db.String(255), nullable=True)
    full_name = db.Column(db.String(100), nullable=True)
    bio = db.Column(db.String(120), nullable=True)
    birthday = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(40), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    message_retention = db.Column(db.String(20), nullable=True, default="off")
    last_active_at = db.Column(db.DateTime, nullable=True)
    show_online_status = db.Column(db.Boolean, nullable=True, default=True)
    show_last_seen = db.Column(db.Boolean, nullable=True, default=True)
    show_read_receipts = db.Column(db.Boolean, nullable=True, default=True)
    allow_messages_from = db.Column(db.String(20), nullable=True, default="friends")
    avatar_visibility = db.Column(db.String(20), nullable=True, default="everyone")
    notifications_enabled = db.Column(db.Boolean, nullable=True, default=True)
    default_chat_theme = db.Column(db.String(20), nullable=True, default="forest")
    appearance_mode = db.Column(db.String(10), nullable=True, default="light")
    created_at = db.Column(db.DateTime, default=utcnow)


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=True)
    pending_message_count = db.Column(db.Integer, nullable=True, default=0)


class UserBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class ChatPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    theme = db.Column(db.String(20), nullable=True, default="forest")


class ConversationArchive(db.Model):
    """A per-user archive marker; it never deletes the underlying messages."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    peer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "peer_id", name="uq_conversation_archive_user_peer"),)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), nullable=True, default="text")
    timestamp = db.Column(db.DateTime, default=utcnow)
    edited_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    delete_after_seen = db.Column(db.Boolean, nullable=True, default=False)
    read_receipt_hidden = db.Column(db.Boolean, nullable=True, default=False)


class Sticker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(80), nullable=False)
    keywords = db.Column(db.String(255), nullable=False, default="")
    value = db.Column(db.String(255), nullable=False)  # emoji glyph or static image path
    sticker_type = db.Column(db.String(10), nullable=False, default="emoji")
    pack = db.Column(db.String(60), nullable=False, default="CHATTI Classics")
    is_active = db.Column(db.Boolean, nullable=True, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class UserSticker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    sticker_id = db.Column(db.Integer, db.ForeignKey("sticker.id"), nullable=False)
    favorite = db.Column(db.Boolean, nullable=False, default=False)
    recent_at = db.Column(db.DateTime, nullable=True)


class StickerShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sticker_id = db.Column(db.Integer, db.ForeignKey("sticker.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class StickerReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sticker_id = db.Column(db.Integer, db.ForeignKey("sticker.id"), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reason = db.Column(db.String(255), nullable=False, default="Inappropriate sticker")
    created_at = db.Column(db.DateTime, default=utcnow)


class Status(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    media_url = db.Column(db.String(255), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)
    background = db.Column(db.String(20), nullable=True, default="forest")
    text_style = db.Column(db.String(20), nullable=True, default="classic")
    timestamp = db.Column(db.DateTime, default=utcnow)


class StatusView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status_id = db.Column(db.Integer, db.ForeignKey("status.id"), nullable=False)
    viewer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    viewed_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("status_id", "viewer_id", name="uq_status_view_status_viewer"),)


class StatusReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status_id = db.Column(db.Integer, db.ForeignKey("status.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reaction = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("status_id", "user_id", name="uq_status_reaction_status_user"),)


class FeedPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    media_url = db.Column(db.String(255), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class FeedComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("feed_post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class FeedReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("feed_post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reaction = db.Column(db.String(20), nullable=False, default="like")
    created_at = db.Column(db.DateTime, default=utcnow)


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


PENDING_REQUEST_MESSAGE_LIMIT = 3


def pending_friend_request(sender_id, receiver_id):
    """Return the unaccepted request that permits a limited DM from its sender."""
    return Friendship.query.filter_by(
        user_id=sender_id, friend_id=receiver_id, status="pending"
    ).first()


def pending_message_remaining(sender_id, receiver_id):
    request_row = pending_friend_request(sender_id, receiver_id)
    if request_row is None:
        return None
    return max(0, PENDING_REQUEST_MESSAGE_LIMIT - int(request_row.pending_message_count or 0))


def reserve_pending_message_slot(sender_id, receiver_id):
    """Atomically reserve a request-message slot in the same transaction as its message."""
    if not can_message(sender_id, receiver_id):
        return False, None

    request_row = pending_friend_request(sender_id, receiver_id)
    if request_row is None:
        return True, None

    request_id = request_row.id
    count = int(request_row.pending_message_count or 0)
    if count >= PENDING_REQUEST_MESSAGE_LIMIT:
        return False, 0

    result = db.session.execute(
        update(Friendship)
        .where(
            Friendship.id == request_id,
            Friendship.status == "pending",
            func.coalesce(Friendship.pending_message_count, 0) < PENDING_REQUEST_MESSAGE_LIMIT,
        )
        .values(pending_message_count=func.coalesce(Friendship.pending_message_count, 0) + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        return True, PENDING_REQUEST_MESSAGE_LIMIT - count - 1

    # A concurrent accept removes the cap; a decline/cancel removes permission.
    db.session.expire_all()
    if can_message(sender_id, receiver_id) and pending_friend_request(sender_id, receiver_id) is None:
        return True, None
    return False, 0


def emit_pending_message_status(sender_id, receiver_id):
    db.session.expire_all()
    request_row = pending_friend_request(sender_id, receiver_id)
    if request_row:
        receiver = db.session.get(User, receiver_id)
        remaining = max(0, PENDING_REQUEST_MESSAGE_LIMIT - int(request_row.pending_message_count or 0))
        payload = {
            "friend_id": receiver_id, "recipient_name": receiver.username if receiver else "your friend",
            "remaining": remaining, "state": "pending",
        }
    elif are_friends(sender_id, receiver_id):
        payload = {"friend_id": receiver_id, "state": "accepted"}
    else:
        payload = {"friend_id": receiver_id, "state": "unavailable"}
    socketio.emit("pending_message_status", payload, to=f"user_{sender_id}")


def is_blocked(a, b):
    if a is None or b is None or a == b:
        return False
    return UserBlock.query.filter(
        ((UserBlock.blocker_id == a) & (UserBlock.blocked_id == b)) |
        ((UserBlock.blocker_id == b) & (UserBlock.blocked_id == a))
    ).first() is not None


def can_message(sender_id, receiver_id):
    if sender_id is None or receiver_id is None or sender_id == receiver_id or is_blocked(sender_id, receiver_id):
        return False
    receiver = db.session.get(User, receiver_id)
    if receiver is None or receiver.allow_messages_from == "nobody":
        return False
    return (receiver.allow_messages_from == "everyone" or are_friends(sender_id, receiver_id)
            or pending_friend_request(sender_id, receiver_id) is not None)


@app.template_global()
def can_view_profile_picture(user):
    if not user or not user.avatar_url:
        return False
    viewer_id = session.get("user_id")
    if viewer_id == user.id:
        return True
    if is_blocked(viewer_id, user.id):
        return False
    visibility = user.avatar_visibility or "everyone"
    if visibility == "everyone":
        return True
    if visibility == "friends":
        return are_friends(viewer_id, user.id)
    return False


@app.template_global()
def current_notifications_enabled():
    viewer_id = session.get("user_id")
    current = db.session.get(User, viewer_id) if viewer_id else None
    return bool(current and current.notifications_enabled is not False)


@app.template_global()
def current_appearance_mode():
    viewer_id = session.get("user_id")
    current = db.session.get(User, viewer_id) if viewer_id else None
    mode = current.appearance_mode if current else "light"
    return mode if mode in {"light", "dark"} else "light"


def room(a, b):
    return f"chat_{min(a, b)}_{max(a, b)}"


def notify_inbox(recipient_id, payload):
    socketio.emit("inbox_message", payload, to=f"user_{recipient_id}")


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
    """(uid, fid) if this socket may message `friend_id`, else (None, None)."""
    uid = socket_user()
    fid = peer_id(data)

    if uid is None or not can_message(uid, fid):
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
    if "user_id" not in session:
        return redirect("/login")
    uid = session["user_id"]
    visible_ids = get_friends(uid) + [uid]
    posts = FeedPost.query.filter(FeedPost.user_id.in_(visible_ids)).order_by(FeedPost.created_at.desc()).all()
    feed_items = []
    for post in posts:
        author = db.session.get(User, post.user_id)
        comments = FeedComment.query.filter_by(post_id=post.id).order_by(FeedComment.created_at.asc()).all()
        comment_items = [(comment, db.session.get(User, comment.user_id)) for comment in comments]
        reactions = FeedReaction.query.filter_by(post_id=post.id).all()
        feed_items.append({
            "post": post, "author": author, "comments": comment_items,
            "reaction_counts": {key: sum(1 for item in reactions if item.reaction == key)
                                for key in ("like", "love", "laugh")},
            "my_reaction": next((item.reaction for item in reactions if item.user_id == uid), None),
        })
    current_user = db.session.get(User, uid)
    return render_template("home.html", feed_items=feed_items, current_user=current_user)


@app.route("/conversations/search")
def search_conversation_messages():
    if "user_id" not in session:
        return jsonify({"peer_ids": []}), 401
    uid = session["user_id"]
    query = (request.args.get("q") or "").strip()[:100]
    if not query:
        return jsonify({"peer_ids": []})
    # Escape SQL LIKE metacharacters so searches are literal.
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    matches = Message.query.filter(
        (Message.sender_id == uid) | (Message.receiver_id == uid),
        Message.content.ilike(f"%{escaped}%", escape="\\"),
        (Message.expires_at.is_(None) | (Message.expires_at > utcnow())),
    ).order_by(Message.timestamp.desc()).limit(250).all()
    peer_ids = set()
    for message in matches:
        peer_id = message.receiver_id if message.sender_id == uid else message.sender_id
        if can_message(uid, peer_id) or can_message(peer_id, uid):
            peer_ids.add(peer_id)
    return jsonify({"peer_ids": list(peer_ids)})


@app.route("/chat/<int:fid>/archive", methods=["POST"])
def archive_conversation(fid):
    if "user_id" not in session:
        return redirect("/login")
    uid = session["user_id"]
    if fid == uid or db.session.get(User, fid) is None:
        abort(404)
    if not (can_message(uid, fid) or can_message(fid, uid)):
        abort(404)
    action = request.form.get("action", "archive")
    if action == "unarchive":
        row = ConversationArchive.query.filter_by(user_id=uid, peer_id=fid).first()
        if row:
            db.session.delete(row)
    elif action == "archive":
        if not ConversationArchive.query.filter_by(user_id=uid, peer_id=fid).first():
            db.session.add(ConversationArchive(user_id=uid, peer_id=fid))
    else:
        abort(400)
    db.session.commit()
    return redirect("/friends?filter=archived" if action == "archive" else "/friends")


def save_social_media(file, folder):
    """Validate and save a supported photo or video upload; return (URL, kind)."""
    if not file or not file.filename:
        return None, None
    mime = (file.mimetype or "").lower()
    signatures = {
        "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        "image/gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        "video/mp4": lambda data: len(data) >= 12 and data[4:8] == b"ftyp",
        "video/webm": lambda data: data.startswith(b"\x1a\x45\xdf\xa3"),
    }
    data = file.read(MAX_STATUS_MEDIA_BYTES + 1)
    if len(data) > MAX_STATUS_MEDIA_BYTES:
        raise ValueError("Choose a photo or video smaller than 25 MB")
    if mime not in signatures or not signatures[mime](data):
        raise ValueError("Choose a JPG, PNG, GIF, WebP, MP4, or WebM file")
    upload_dir = os.path.join(app.static_folder, "uploads", folder)
    os.makedirs(upload_dir, exist_ok=True)
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                 "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm"}[mime]
    filename = f"{uuid.uuid4().hex}.{extension}"
    with open(os.path.join(upload_dir, filename), "wb") as uploaded_file:
        uploaded_file.write(data)
    return f"/static/uploads/{folder}/{filename}", mime.split("/", 1)[0]


@app.route("/posts", methods=["POST"])
def create_feed_post():
    if "user_id" not in session:
        return redirect("/login")
    content = (request.form.get("content") or "").strip()
    if len(content) > 3000:
        flash("Posts must be 3,000 characters or fewer", "error")
        return redirect("/")
    try:
        media_url, media_type = save_social_media(request.files.get("media_file"), "posts")
    except ValueError as error:
        flash(str(error), "error")
        return redirect("/")
    if not content and not media_url:
        flash("Write something or add a photo or video", "error")
        return redirect("/")
    db.session.add(FeedPost(user_id=session["user_id"], content=content,
                            media_url=media_url, media_type=media_type))
    db.session.commit()
    flash("Your post is on the feed", "success")
    return redirect("/")


@app.route("/posts/<int:post_id>/react", methods=["POST"])
def react_to_post(post_id):
    if "user_id" not in session:
        return redirect("/login")
    uid = session["user_id"]
    post = db.session.get(FeedPost, post_id)
    if not post or (post.user_id != uid and not are_friends(uid, post.user_id)):
        abort(404)
    reaction = request.form.get("reaction", "like")
    if reaction not in {"like", "love", "laugh"}:
        abort(400)
    existing = FeedReaction.query.filter_by(post_id=post_id, user_id=uid).first()
    if existing and existing.reaction == reaction:
        db.session.delete(existing)
    elif existing:
        existing.reaction = reaction
    else:
        db.session.add(FeedReaction(post_id=post_id, user_id=uid, reaction=reaction))
    db.session.commit()
    return redirect("/")


@app.route("/posts/<int:post_id>/comment", methods=["POST"])
def comment_on_post(post_id):
    if "user_id" not in session:
        return redirect("/login")
    uid = session["user_id"]
    post = db.session.get(FeedPost, post_id)
    if not post or (post.user_id != uid and not are_friends(uid, post.user_id)):
        abort(404)
    content = (request.form.get("content") or "").strip()
    if content and len(content) <= 1000:
        db.session.add(FeedComment(post_id=post_id, user_id=uid, content=content))
        db.session.commit()
    return redirect("/#post-" + str(post_id))


@app.route("/posts/<int:post_id>/delete", methods=["POST"])
def delete_feed_post(post_id):
    if "user_id" not in session:
        return redirect("/login")
    post = db.session.get(FeedPost, post_id)
    if post and post.user_id == session["user_id"]:
        FeedComment.query.filter_by(post_id=post_id).delete()
        FeedReaction.query.filter_by(post_id=post_id).delete()
        db.session.delete(post)
        db.session.commit()
    return redirect("/")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not username or not email or not password:
            flash("Username, email, and password are required", "error")
            return redirect("/signup")

        if len(password) > 8:
            flash("Password cannot be more than 8 characters.", "error")
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
        password = request.form.get("password") or ""
        if len(password) > 8:
            flash("Password cannot be more than 8 characters.", "error")
            return redirect("/login")
        user = User.query.filter_by(
            username=(request.form.get("username") or "").strip()
        ).first()

        if user and check_password_hash(user.password, password):
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
    return redirect("/logged-out")


@app.route("/appearance", methods=["POST"])
def update_appearance():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Please log in"}), 401
    data = request.get_json(silent=True) or request.form
    mode = data.get("mode")
    if mode not in {"light", "dark"}:
        return jsonify({"ok": False, "error": "Choose light or dark mode"}), 400
    user = db.session.get(User, session["user_id"])
    if user is None:
        session.clear()
        return jsonify({"ok": False, "error": "Please log in"}), 401
    user.appearance_mode = mode
    db.session.commit()
    return jsonify({"ok": True, "mode": mode})


@app.route("/logged-out")
def logged_out():
    return render_template("logged_out.html")


@app.route("/friends")
def friends():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    ids = get_friends(uid)
    message_peer_ids = {row[0] for row in db.session.query(Message.sender_id).filter_by(receiver_id=uid).all()}
    message_peer_ids.update(row[0] for row in db.session.query(Message.receiver_id).filter_by(sender_id=uid).all())
    archive_rows = ConversationArchive.query.filter_by(user_id=uid).all()
    archived_ids = {row.peer_id for row in archive_rows}
    conversation_ids = set(ids) | message_peer_ids | archived_ids
    conversation_users = User.query.filter(User.id.in_(conversation_ids)).all() if conversation_ids else []
    conversation_users = [person for person in conversation_users
                          if can_message(uid, person.id) or can_message(person.id, uid)]
    now = utcnow()
    conversations = []
    for friend in conversation_users:
        conversation_filter = (
            ((Message.sender_id == uid) & (Message.receiver_id == friend.id)) |
            ((Message.sender_id == friend.id) & (Message.receiver_id == uid))
        )
        available = Message.expires_at.is_(None) | (Message.expires_at > now)
        latest = Message.query.filter(conversation_filter, available).order_by(Message.timestamp.desc(), Message.id.desc()).first()
        unread_count = Message.query.filter_by(sender_id=friend.id, receiver_id=uid, read_at=None).filter(available).count()
        if latest is None:
            preview = "Start a conversation"
            timestamp = None
            time_label = ""
        else:
            timestamp = latest.timestamp
            if latest.message_type == "image":
                preview = "Sent you a photo 📷" if latest.sender_id != uid else "You sent a photo 📷"
            elif latest.message_type == "video":
                preview = "Sent you a video 🎥" if latest.sender_id != uid else "You sent a video 🎥"
            elif latest.message_type == "audio":
                preview = "Sent a voice message 🎙️" if latest.sender_id != uid else "You sent a voice message 🎙️"
            elif latest.message_type == "sticker":
                preview = "Sent a sticker ✨" if latest.sender_id != uid else "You sent a sticker ✨"
            else:
                preview = ("You: " if latest.sender_id == uid else "") + latest.content
            if timestamp and timestamp.date() == now.date():
                time_label = timestamp.strftime("%H:%M")
            elif timestamp and timestamp.date() == (now - timedelta(days=1)).date():
                time_label = "Yesterday"
            elif timestamp:
                time_label = timestamp.strftime("%A")
            else:
                time_label = ""
        conversations.append({
            "friend": friend, "preview": preview, "timestamp": timestamp,
            "time_label": time_label, "unread_count": unread_count,
            "archived": friend.id in archived_ids,
        })
    conversations.sort(key=lambda item: item["timestamp"] or datetime.min, reverse=True)

    return render_template(
        "chats.html", conversations=conversations, online_users=visible_online_user_ids(uid),
    )


def people_directory_context(uid):
    ids = get_friends(uid)
    people_friends = User.query.filter(User.id.in_(ids)).order_by(User.username).all() if ids else []
    block_rows = UserBlock.query.filter((UserBlock.blocker_id == uid) | (UserBlock.blocked_id == uid)).all()
    hidden_account_ids = {row.blocker_id if row.blocked_id == uid else row.blocked_id for row in block_rows}
    accounts = [account for account in User.query.filter(User.id != uid).order_by(User.username).all()
                if account.id not in hidden_account_ids]
    discover_accounts = [account for account in accounts if account.id not in set(ids)]
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
    return {
        "friends": people_friends,
        "accounts": accounts,
        "discover_accounts": discover_accounts,
        "friend_ids": set(ids),
        "incoming_requests": incoming_requests,
        "incoming_request_by_user": incoming_request_by_user,
        "outgoing_ids": outgoing_ids,
        "online_users": visible_online_user_ids(uid),
    }


@app.route("/people")
def people():
    if "user_id" not in session:
        return redirect("/login")
    return render_template(
        "friends.html", **people_directory_context(session["user_id"]),
        active_people_tab="friends",
    )


@app.route("/explore")
def explore():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("explore.html", current_user=db.session.get(User, session["user_id"]))


def friend_action_redirect():
    destination = request.form.get("return_to", "/friends")
    if destination not in {"/people", "/friends"}:
        destination = "/friends"
    return redirect(destination)


@app.route("/add_friend", methods=["POST"])
def add_friend():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    username = (request.form.get("username") or "").strip()

    if not username:
        flash("Enter a username", "error")
        return friend_action_redirect()

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
    elif is_blocked(uid, other.id):
        flash("You cannot add this person while either account has blocked the other", "error")
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

    return friend_action_redirect()


@app.route("/friend_request/<int:request_id>/<action>", methods=["POST"])
def respond_friend_request(request_id, action):
    if "user_id" not in session:
        return redirect("/login")
    if action not in {"accept", "decline"}:
        abort(404)

    friend_request = Friendship.query.filter_by(
        id=request_id, friend_id=session["user_id"], status="pending"
    ).first_or_404()
    requester_id, recipient_id = friend_request.user_id, friend_request.friend_id
    requester = db.session.get(User, friend_request.user_id)
    if action == "accept":
        friend_request.status = "accepted"
        flash(f"You and {requester.username} are now friends", "success")
    else:
        db.session.delete(friend_request)
        flash("Friend request declined", "success")
    db.session.commit()
    emit_pending_message_status(requester_id, recipient_id)
    return friend_action_redirect()


@app.route("/remove_friend/<int:fid>", methods=["POST"])
def remove_friend(fid):
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    rows = Friendship.query.filter(
        ((Friendship.user_id == uid) & (Friendship.friend_id == fid)) |
        ((Friendship.user_id == fid) & (Friendship.friend_id == uid))
    ).all()
    pending_senders = [(row.user_id, row.friend_id) for row in rows if row.status == "pending"]
    if rows:
        for row in rows:
            db.session.delete(row)
        db.session.commit()
        flash("Friend removed", "success")
        for sender_id, receiver_id in pending_senders:
            emit_pending_message_status(sender_id, receiver_id)
    return friend_action_redirect()


@app.route("/status", methods=["GET", "POST"])
def status_page():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    if request.method == "POST":
        content = (request.form.get("content") or "").strip()
        media_files = [item for item in request.files.getlist("media_files") if item and item.filename]
        # Continue accepting the original single-file field for older clients.
        if not media_files:
            legacy_file = request.files.get("media_file")
            if legacy_file and legacy_file.filename:
                media_files = [legacy_file]
        if len(media_files) > 10:
            flash("You can share up to 10 items in one update", "error")
            return redirect("/status")
        background = request.form.get("background", "forest")
        text_style = request.form.get("text_style", "classic")
        allowed_backgrounds = {"forest", "ocean", "sunset", "rose", "violet", "gold"}
        allowed_styles = {"classic", "bold", "serif"}
        if background not in allowed_backgrounds:
            background = "forest"
        if text_style not in allowed_styles:
            text_style = "classic"
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
        uploaded = []
        upload_error = None
        for media_file in media_files:
            media_bytes = media_file.read(MAX_STATUS_MEDIA_BYTES + 1)
            media_mime = (media_file.mimetype or "").lower()
            if len(media_bytes) > MAX_STATUS_MEDIA_BYTES:
                upload_error = "Choose photos, videos, or audio smaller than 25 MB each"
                break
            if media_mime not in signatures or not signatures[media_mime](media_bytes):
                upload_error = "Choose valid JPG, PNG, GIF, WebP, MP4, WebM, MP3, M4A, OGG, or WAV media"
                break
            uploaded.append((media_file, media_bytes, media_mime))

        if upload_error:
            flash(upload_error, "error")
        elif not content and not uploaded:
            flash("Write an update or add a photo, video, or audio file", "error")
        elif len(content) > 500:
            flash("Update must be 500 characters or fewer", "error")
        else:
            if not uploaded:
                uploaded = [(None, None, None)]
            for media_file, media_bytes, media_mime in uploaded:
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
                    media_url=media_url, media_type=media_type,
                    background=background, text_style=text_style
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
    status_ids = [status.id for status, _author in statuses]
    seen_ids = {row.status_id for row in StatusView.query.filter(
        StatusView.viewer_id == uid, StatusView.status_id.in_(status_ids)
    ).all()} if status_ids else set()
    reaction_rows = StatusReaction.query.filter(StatusReaction.status_id.in_(status_ids)).all() if status_ids else []
    reaction_counts = {}
    my_reactions = {}
    for row in reaction_rows:
        counts = reaction_counts.setdefault(row.status_id, {})
        counts[row.reaction] = counts.get(row.reaction, 0) + 1
        if row.user_id == uid:
            my_reactions[row.status_id] = row.reaction

    viewer_stories = []
    grouped_stories = {}
    for status, author in statuses:
        created_at = status.timestamp or utcnow()
        expires_at = created_at + timedelta(hours=12)
        item = {
            "id": status.id,
            "user_id": author.id,
            "author": "You" if author.id == uid else author.username,
            "username": author.username,
            "avatar_url": url_for("user_avatar", user_id=author.id) if can_view_profile_picture(author) else None,
            "initial": (author.username or "?")[0].upper(),
            "content": status.content or "",
            "media_url": status.media_url or "",
            "media_type": status.media_type or "",
            "background": status.background or "forest",
            "text_style": status.text_style or "classic",
            "timestamp": created_at.isoformat() + "Z",
            "time_label": created_at.strftime("%b %d, %H:%M") + " UTC",
            "expires_at": expires_at.isoformat() + "Z",
            "delete_url": url_for("delete_status", status_id=status.id) if author.id == uid else "",
            "seen": status.id in seen_ids or author.id == uid,
            "reactions": reaction_counts.get(status.id, {}),
            "my_reaction": my_reactions.get(status.id, ""),
        }
        viewer_stories.append(item)
        group = grouped_stories.get(author.id)
        if group is None:
            group = {"user_id": author.id, "username": author.username,
                     "initial": item["initial"], "avatar_url": item["avatar_url"],
                     "unseen": False, "start_index": len(viewer_stories) - 1}
            grouped_stories[author.id] = group
        if not item["seen"]:
            group["unseen"] = True

    return render_template(
        "status.html", own_statuses=own_statuses,
        friend_statuses=friend_statuses, current_user_id=uid,
        current_user=db.session.get(User, uid), viewer_stories=viewer_stories,
        story_authors=list(grouped_stories.values()),
    )


@app.post("/status/<int:status_id>/view")
def view_status(status_id):
    uid = session.get("user_id")
    if uid is None:
        return jsonify(ok=False, error="Sign in to view updates"), 401
    status = db.session.get(Status, status_id)
    cutoff = utcnow() - timedelta(hours=12)
    if not status or status.timestamp < cutoff or (status.user_id != uid and
            (status.user_id not in get_friends(uid) or is_blocked(uid, status.user_id))):
        return jsonify(ok=False, error="This update is no longer available"), 404
    if status.user_id != uid and not StatusView.query.filter_by(status_id=status_id, viewer_id=uid).first():
        db.session.add(StatusView(status_id=status_id, viewer_id=uid))
        db.session.commit()
    return jsonify(ok=True)


@app.post("/status/<int:status_id>/react")
def react_to_status(status_id):
    uid = session.get("user_id")
    if uid is None:
        return jsonify(ok=False, error="Sign in to react"), 401
    status = db.session.get(Status, status_id)
    allowed = {"❤️", "😂", "😮", "😢", "👏", "🔥"}
    reaction = (request.get_json(silent=True) or {}).get("reaction", "")
    if not status or status.timestamp < utcnow() - timedelta(hours=12) or (
            status.user_id != uid and (status.user_id not in get_friends(uid) or is_blocked(uid, status.user_id))):
        return jsonify(ok=False, error="This update is no longer available"), 404
    if reaction not in allowed:
        return jsonify(ok=False, error="Choose a supported reaction"), 400
    existing = StatusReaction.query.filter_by(status_id=status_id, user_id=uid).first()
    if existing and existing.reaction == reaction:
        db.session.delete(existing)
        mine = ""
    elif existing:
        existing.reaction = reaction
        existing.created_at = utcnow()
        mine = reaction
    else:
        db.session.add(StatusReaction(status_id=status_id, user_id=uid, reaction=reaction))
        mine = reaction
    db.session.commit()
    rows = StatusReaction.query.filter_by(status_id=status_id).all()
    counts = {}
    for row in rows:
        counts[row.reaction] = counts.get(row.reaction, 0) + 1
    payload = {"status_id": status_id, "counts": counts}
    socketio.emit("status_reaction", payload, to=f"user_{status.user_id}")
    return jsonify(ok=True, my_reaction=mine, counts=counts)


@app.post("/status/<int:status_id>/reply")
def reply_to_status(status_id):
    uid = session.get("user_id")
    if uid is None:
        return jsonify(ok=False, error="Sign in to reply"), 401
    status = db.session.get(Status, status_id)
    content = ((request.get_json(silent=True) or {}).get("content") or "").strip()
    if not status or status.user_id == uid or status.timestamp < utcnow() - timedelta(hours=12) or (
            status.user_id not in get_friends(uid) or is_blocked(uid, status.user_id)):
        return jsonify(ok=False, error="This update is no longer available"), 404
    if not content:
        return jsonify(ok=False, error="Write a reply first"), 400
    if len(content) > MAX_MESSAGE_LEN:
        return jsonify(ok=False, error=f"Reply must be {MAX_MESSAGE_LEN} characters or fewer"), 400
    if not can_message(uid, status.user_id):
        return jsonify(ok=False, error="This person is not accepting private messages"), 403
    allowed, remaining = reserve_pending_message_slot(uid, status.user_id)
    if not allowed:
        return jsonify(ok=False, error="You can't send more messages until your friend accepts your request."), 403
    now = utcnow()
    sender = db.session.get(User, uid)
    recipient = db.session.get(User, status.user_id)
    room_name = room(uid, status.user_id)
    recipient_is_viewing = bool(chat_room_viewers.get(room_name, {}).get(status.user_id))
    retention = sender.message_retention if sender else "off"
    message = Message(sender_id=uid, receiver_id=status.user_id, content=content,
                      message_type="text", timestamp=now, expires_at=message_expiry(retention, now),
                      delete_after_seen=retention == "seen",
                      read_receipt_hidden=bool(recipient_is_viewing and recipient and recipient.show_read_receipts is False))
    if recipient_is_viewing:
        message.delivered_at = now
        message.read_at = now
    db.session.add(message)
    db.session.commit()
    if remaining is not None:
        emit_pending_message_status(uid, status.user_id)
    payload = {"id": message.id, "content": message.content, "message_type": "text",
               "sender_id": uid, "receiver_id": status.user_id, "time": now.strftime("%H:%M"),
               "receipt": "seen" if message.read_at and not message.read_receipt_hidden else
                         ("delivered" if message.delivered_at else "sent"),
               "expires_at": message.expires_at.isoformat() if message.expires_at else None}
    socketio.emit("receive_message", payload, room=room_name)
    notify_inbox(status.user_id, {"sender_id": uid, "receiver_id": status.user_id,
                                  "content": content, "message_type": "text"})
    if recipient_is_viewing and retention == "seen":
        db.session.delete(message)
        db.session.commit()
        socketio.emit("message_deleted", {"id": message.id}, room=room_name)
    return jsonify(ok=True, message="Private reply sent")


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
    if not is_owner and is_blocked(current_id, target_id):
        abort(404)
    if not is_owner and not are_friends(current_id, target_id):
        abort(403)
    back_chat_id = request.args.get("from_chat", type=int)
    if back_chat_id != target_id or not are_friends(current_id, target_id):
        back_chat_id = None
    if request.method == "POST" and not is_owner:
        abort(403)

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        username = (request.form.get("username") or "").strip()
        bio = (request.form.get("bio") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        birthday_raw = (request.form.get("birthday") or "").strip()
        gender = (request.form.get("gender") or "").strip()
        location = (request.form.get("location") or "").strip()
        birthday = None
        birthday_invalid = False
        if birthday_raw:
            try:
                birthday = date.fromisoformat(birthday_raw)
                birthday_invalid = birthday > date.today()
            except ValueError:
                birthday_invalid = True
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
        elif not username or len(username) > 50:
            flash("Username must be between 1 and 50 characters", "error")
        elif User.query.filter(User.username == username, User.id != user.id).first():
            flash("That username is already in use", "error")
        elif len(full_name) > 100:
            flash("Full name must be 100 characters or fewer", "error")
        elif birthday_invalid:
            flash("Enter a valid birthday that is not in the future", "error")
        elif len(gender) > 40:
            flash("Gender must be 40 characters or fewer", "error")
        elif len(location) > 120:
            flash("Location must be 120 characters or fewer", "error")
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
            user.full_name = full_name or None
            user.username = username
            user.email = email or None
            user.bio = bio
            user.birthday = birthday
            user.gender = gender or None
            user.location = location or None
            db.session.commit()
            flash("Profile updated", "success")
            return redirect("/profile")

    return render_template(
        "profile.html", user=user, is_owner=is_owner,
        online_users=(online_user_ids() if is_owner else visible_online_user_ids(session.get("user_id"))),
        self_is_online=(user.id in online_user_ids()),
        back_chat_id=back_chat_id, today_iso=date.today().isoformat()
    )


@app.route("/avatar/<int:user_id>")
def user_avatar(user_id):
    if "user_id" not in session:
        abort(401)
    user = db.session.get(User, user_id)
    if not user or not can_view_profile_picture(user):
        abort(404)
    relative_path = (user.avatar_url or "").removeprefix("/static/")
    if not relative_path.startswith("uploads/"):
        abort(404)
    return send_from_directory(app.static_folder, relative_path)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])
    if request.method == "POST":
        section = request.form.get("section")
        if section == "presence":
            user.show_online_status = request.form.get("show_online_status") == "on"
            user.show_last_seen = request.form.get("show_last_seen") == "on"
            user.show_read_receipts = request.form.get("show_read_receipts") == "on"
            db.session.commit()
            active = user.id in online_user_ids()
            payload = {
                "user_id": user.id,
                "status": "online" if active and user.show_online_status else "offline",
                "last_active_at": user.last_active_at.isoformat() + "Z" if user.last_active_at and user.show_last_seen else "",
            }
            socketio.emit("user_status", payload, broadcast=True)
            flash("Privacy settings saved.", "success")
            return redirect("/settings")

        if section == "privacy":
            messages_from = request.form.get("allow_messages_from")
            avatar_visibility = request.form.get("avatar_visibility")
            if messages_from not in {"everyone", "friends", "nobody"} or avatar_visibility not in {"everyone", "friends", "nobody"}:
                flash("Choose valid privacy options.", "error")
            else:
                user.allow_messages_from = messages_from
                user.avatar_visibility = avatar_visibility
                db.session.commit()
                flash("Privacy choices saved.", "success")
                return redirect("/settings")

        if section == "notifications":
            user.notifications_enabled = request.form.get("notifications_enabled") == "on"
            db.session.commit()
            flash("Notification settings saved.", "success")
            return redirect("/settings")

        if section == "theme":
            theme = request.form.get("default_chat_theme")
            if theme not in CHAT_THEMES:
                flash("Choose a valid default chat theme.", "error")
            else:
                user.default_chat_theme = theme
                db.session.commit()
                flash("Default chat theme saved. Existing chat-specific choices stay as they are.", "success")
                return redirect("/settings")

        if section == "password":
            current_password = request.form.get("current_password") or ""
            new_password = request.form.get("new_password") or ""
            confirm_password = request.form.get("confirm_password") or ""
            if not check_password_hash(user.password, current_password):
                flash("Your current password is incorrect.", "error")
            elif not valid_new_password(new_password):
                flash("New passwords must be exactly 6 or 8 letters or numbers, with no spaces or symbols.", "error")
            elif new_password != confirm_password:
                flash("The new passwords do not match.", "error")
            else:
                user.password = generate_password_hash(new_password)
                db.session.commit()
                flash("Password changed successfully.", "success")
                return redirect("/settings")

        if section == "delete_account":
            password = request.form.get("delete_password") or ""
            if not check_password_hash(user.password, password):
                flash("Enter your current password to delete your account.", "error")
            elif request.form.get("confirm_delete") != "on":
                flash("Confirm that you want to permanently delete your account.", "error")
            else:
                delete_user_account(user)
                session.clear()
                return redirect("/logged-out")

        if section == "retention":
            retention = request.form.get("message_retention", "off")
            if retention not in {"seen", "12h", "24h", "30d", "off"}:
                flash("Choose a valid message retention option", "error")
            else:
                user.message_retention = retention
                db.session.commit()
                flash("Message retention setting saved. It applies to new messages you send.", "success")
                return redirect("/settings")

    blocked_rows = UserBlock.query.filter_by(blocker_id=user.id).all()
    blocked_users = [db.session.get(User, row.blocked_id) for row in blocked_rows]
    blocked_users = [person for person in blocked_users if person]
    blocked_ids = {person.id for person in blocked_users}
    all_accounts = User.query.filter(User.id != user.id).order_by(User.username).all()
    return render_template("settings.html", user=user, chat_themes=CHAT_THEMES,
                           blocked_users=blocked_users, blocked_ids=blocked_ids,
                           all_accounts=all_accounts)


def delete_user_account(user):
    uid = user.id
    posts = FeedPost.query.filter_by(user_id=uid).all()
    statuses = Status.query.filter_by(user_id=uid).all()
    owned_stickers = Sticker.query.filter_by(owner_id=uid).all()
    post_ids = [row.id for row in posts]
    owned_sticker_ids = [row.id for row in owned_stickers]
    uploaded_media = [user.avatar_url]
    uploaded_media.extend(row.media_url for row in posts)
    uploaded_media.extend(row.media_url for row in statuses)
    uploaded_media.extend(
        row.value for row in owned_stickers if row.sticker_type == "image"
    )

    for viewers in chat_room_viewers.values():
        viewers.pop(uid, None)
    for sid in online_sessions.pop(uid, set()):
        socketio.server.disconnect(sid, namespace="/")

    Message.query.filter((Message.sender_id == uid) | (Message.receiver_id == uid)).delete(synchronize_session=False)
    Friendship.query.filter((Friendship.user_id == uid) | (Friendship.friend_id == uid)).delete(synchronize_session=False)
    UserBlock.query.filter((UserBlock.blocker_id == uid) | (UserBlock.blocked_id == uid)).delete(synchronize_session=False)
    ChatPreference.query.filter((ChatPreference.user_id == uid) | (ChatPreference.friend_id == uid)).delete(synchronize_session=False)
    ConversationArchive.query.filter((ConversationArchive.user_id == uid) | (ConversationArchive.peer_id == uid)).delete(synchronize_session=False)
    Status.query.filter_by(user_id=uid).delete(synchronize_session=False)
    FeedComment.query.filter((FeedComment.user_id == uid) | (FeedComment.post_id.in_(post_ids) if post_ids else False)).delete(synchronize_session=False)
    FeedReaction.query.filter((FeedReaction.user_id == uid) | (FeedReaction.post_id.in_(post_ids) if post_ids else False)).delete(synchronize_session=False)
    FeedPost.query.filter_by(user_id=uid).delete(synchronize_session=False)
    UserSticker.query.filter((UserSticker.user_id == uid) | (UserSticker.sticker_id.in_(owned_sticker_ids) if owned_sticker_ids else False)).delete(synchronize_session=False)
    StickerShare.query.filter((StickerShare.user_id == uid) | (StickerShare.sticker_id.in_(owned_sticker_ids) if owned_sticker_ids else False)).delete(synchronize_session=False)
    StickerReport.query.filter((StickerReport.reporter_id == uid) | (StickerReport.sticker_id.in_(owned_sticker_ids) if owned_sticker_ids else False)).delete(synchronize_session=False)
    Sticker.query.filter_by(owner_id=uid).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()

    # Remove files owned by the deleted account after the database transaction
    # succeeds. Only paths beneath static/uploads are eligible for cleanup.
    uploads_root = os.path.realpath(os.path.join(app.static_folder, "uploads"))
    for media_url in uploaded_media:
        if not media_url or not media_url.startswith("/static/uploads/"):
            continue
        file_path = os.path.realpath(os.path.join(app.static_folder, media_url.removeprefix("/static/")))
        if os.path.commonpath((uploads_root, file_path)) != uploads_root:
            continue
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except OSError:
            app.logger.warning("Could not remove uploaded file during account deletion: %s", file_path)


@app.route("/settings/block", methods=["POST"])
def block_user():
    if "user_id" not in session:
        return redirect("/login")
    uid = session["user_id"]
    try:
        blocked_id = int(request.form.get("user_id", ""))
    except (TypeError, ValueError):
        flash("Choose an account to block.", "error")
        return redirect("/settings")
    if blocked_id == uid or db.session.get(User, blocked_id) is None:
        flash("That account cannot be blocked.", "error")
        return redirect("/settings")
    if not UserBlock.query.filter_by(blocker_id=uid, blocked_id=blocked_id).first():
        db.session.add(UserBlock(blocker_id=uid, blocked_id=blocked_id))
        Friendship.query.filter(
            ((Friendship.user_id == uid) & (Friendship.friend_id == blocked_id)) |
            ((Friendship.user_id == blocked_id) & (Friendship.friend_id == uid))
        ).delete(synchronize_session=False)
        db.session.commit()
    flash("Account blocked. They can no longer message or find your profile.", "success")
    return redirect("/settings")


@app.route("/settings/unblock/<int:user_id>", methods=["POST"])
def unblock_user(user_id):
    if "user_id" not in session:
        return redirect("/login")
    row = UserBlock.query.filter_by(blocker_id=session["user_id"], blocked_id=user_id).first()
    if row:
        db.session.delete(row)
        db.session.commit()
        flash("Account unblocked.", "success")
    return redirect("/settings")


@app.route("/chat/<int:fid>")
def chat(fid):
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    friend = db.session.get(User, fid)

    if friend is None:
        abort(404)

    if not (can_message(uid, fid) or can_message(fid, uid)):
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

    online_users = visible_online_user_ids(uid)
    friend_online = friend.id in online_users
    preference = ChatPreference.query.filter_by(user_id=uid, friend_id=fid).first()
    theme_name = preference.theme if preference and preference.theme in CHAT_THEMES else (db.session.get(User, uid).default_chat_theme or "forest")
    ensure_sticker_library()
    stickers = Sticker.query.filter(Sticker.is_active.isnot(False)).filter(
        (Sticker.owner_id.is_(None)) | (Sticker.owner_id == uid) |
        (Sticker.id.in_(db.session.query(StickerShare.sticker_id).filter_by(user_id=uid)))
    ).order_by(Sticker.owner_id.isnot(None), Sticker.pack, Sticker.name).all()
    sticker_ids = [item.id for item in stickers]
    user_stickers = UserSticker.query.filter_by(user_id=uid).filter(UserSticker.sticker_id.in_(sticker_ids)).all() if sticker_ids else []
    sticker_preferences = {item.sticker_id: item for item in user_stickers}
    sticker_map = {item.id: item for item in Sticker.query.filter(
        Sticker.id.in_([int(m.content) for m in messages if m.message_type == "sticker" and m.content.isdigit()])
    ).all()} if any(m.message_type == "sticker" and m.content.isdigit() for m in messages) else {}
    pending_remaining = pending_message_remaining(uid, fid)
    return render_template(
        "chat.html",
        friend=friend,
        friends=sidebar,
        messages=messages,
        current_user_id=uid,
        online_users=online_users,
        friend_activity=activity_label(friend, friend_online) if friend_online or friend.show_last_seen is not False else "Offline",
        chat_theme_name=theme_name,
        chat_theme=CHAT_THEMES[theme_name],
        chat_themes=CHAT_THEMES,
        stickers=stickers,
        sticker_preferences=sticker_preferences,
        sticker_map=sticker_map,
        pending_message_remaining=pending_remaining,
    )


def ensure_sticker_library():
    existing = {item.name for item in Sticker.query.filter_by(owner_id=None).all()}
    for name, keywords, emoji, pack in STICKER_SEEDS:
        if name not in existing:
            db.session.add(Sticker(name=name, keywords=keywords, value=emoji,
                                   sticker_type="emoji", pack=pack))
    if len(existing) < len(STICKER_SEEDS):
        db.session.commit()


@app.route("/stickers/upload", methods=["POST"])
def upload_sticker():
    if "user_id" not in session:
        return redirect("/login")
    return_to = request.form.get("return_to", "/friends")
    if not return_to.startswith("/") or return_to.startswith("//"):
        return_to = "/friends"
    file = request.files.get("sticker_file")
    if not file or not file.filename:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(ok=False, error="Choose an image to make a sticker"), 400
        flash("Choose an image to make a sticker", "error")
        return redirect(return_to)
    mime = (file.mimetype or "").lower()
    signatures = {
        "image/png": ("png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
        "image/jpeg": ("jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
        "image/webp": ("webp", lambda b: b.startswith(b"RIFF") and b[8:12] == b"WEBP"),
        "image/gif": ("gif", lambda b: b.startswith((b"GIF87a", b"GIF89a"))),
    }
    data = file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024 or mime not in signatures or not signatures[mime][1](data):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(ok=False, error="Use a valid PNG, JPG, WebP, or animated GIF under 5 MB"), 400
        flash("Use a valid PNG, JPG, WebP, or animated GIF under 5 MB", "error")
        return redirect(return_to)
    folder = os.path.join(app.static_folder, "uploads", "stickers")
    os.makedirs(folder, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{signatures[mime][0]}"
    with open(os.path.join(folder, filename), "wb") as image_file:
        image_file.write(data)
    name = (request.form.get("name") or "My sticker").strip()[:80] or "My sticker"
    keywords = (request.form.get("keywords") or name).strip()[:255]
    pack = (request.form.get("pack") or "My stickers").strip()[:60] or "My stickers"
    sticker = Sticker(owner_id=session["user_id"], name=name, keywords=keywords,
                      value=f"/static/uploads/stickers/{filename}",
                      sticker_type="image", pack=pack)
    db.session.add(sticker)
    db.session.flush()
    db.session.add(UserSticker(user_id=session["user_id"], sticker_id=sticker.id, favorite=True))
    db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=True, sticker={"id": sticker.id, "name": sticker.name,
            "keywords": sticker.keywords, "value": sticker.value, "type": sticker.sticker_type,
            "pack": sticker.pack, "favorite": True})
    flash("Sticker added to My stickers", "success")
    return redirect(return_to)


@app.route("/stickers/<int:sticker_id>/favorite", methods=["POST"])
def favorite_sticker(sticker_id):
    if "user_id" not in session:
        return jsonify(ok=False), 401
    uid = session["user_id"]
    visible = Sticker.query.filter_by(id=sticker_id).filter(Sticker.is_active.isnot(False)).filter(
        (Sticker.owner_id.is_(None)) | (Sticker.owner_id == uid) |
        (Sticker.id.in_(db.session.query(StickerShare.sticker_id).filter_by(user_id=uid)))
    ).first()
    if not visible:
        return jsonify(ok=False), 404
    preference = UserSticker.query.filter_by(user_id=uid, sticker_id=sticker_id).first()
    if preference is None:
        preference = UserSticker(user_id=uid, sticker_id=sticker_id, favorite=True)
        db.session.add(preference)
    else:
        preference.favorite = not preference.favorite
    db.session.commit()
    return jsonify(ok=True, favorite=preference.favorite)


@app.route("/stickers/<int:sticker_id>/report", methods=["POST"])
def report_sticker(sticker_id):
    if "user_id" not in session:
        return jsonify(ok=False), 401
    sticker = db.session.get(Sticker, sticker_id)
    if not sticker or sticker.is_active is False or sticker.owner_id is None or sticker.owner_id == session["user_id"]:
        return jsonify(ok=False), 404
    if not StickerShare.query.filter_by(sticker_id=sticker_id, user_id=session["user_id"]).first():
        return jsonify(ok=False), 404
    db.session.add(StickerReport(sticker_id=sticker_id, reporter_id=session["user_id"],
                                 reason=(request.json or {}).get("reason", "Inappropriate sticker")[:255]))
    db.session.commit()
    return jsonify(ok=True)


@app.route("/stickers/<int:sticker_id>/delete", methods=["POST"])
def delete_sticker(sticker_id):
    if "user_id" not in session:
        return jsonify(ok=False), 401
    sticker = db.session.get(Sticker, sticker_id)
    if not sticker or sticker.owner_id != session["user_id"]:
        return jsonify(ok=False), 404
    sticker.is_active = False
    db.session.commit()
    return jsonify(ok=True)


@app.route("/stickers/packs/delete", methods=["POST"])
def delete_sticker_pack():
    if "user_id" not in session:
        return jsonify(ok=False), 401
    pack = ((request.json or {}).get("pack") or "").strip()[:60]
    if not pack:
        return jsonify(ok=False), 400
    owned = Sticker.query.filter_by(owner_id=session["user_id"], pack=pack).filter(
        Sticker.is_active.isnot(False)
    ).all()
    if not owned:
        return jsonify(ok=False), 404
    for sticker in owned:
        sticker.is_active = False
    db.session.commit()
    return jsonify(ok=True, count=len(owned))


@app.route("/stickers/packs/share", methods=["POST"])
def share_sticker_pack():
    if "user_id" not in session:
        return jsonify(ok=False), 401
    data = request.get_json(silent=True) or {}
    pack = (data.get("pack") or "").strip()[:60]
    try:
        friend_id = int(data.get("friend_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False), 400
    uid = session["user_id"]
    if not pack or not are_friends(uid, friend_id):
        return jsonify(ok=False), 403
    stickers = Sticker.query.filter_by(owner_id=uid, pack=pack).filter(
        Sticker.is_active.isnot(False)
    ).all()
    if not stickers:
        return jsonify(ok=False), 404
    for sticker in stickers:
        if not StickerShare.query.filter_by(sticker_id=sticker.id, user_id=friend_id).first():
            db.session.add(StickerShare(sticker_id=sticker.id, user_id=friend_id))
        if not UserSticker.query.filter_by(user_id=friend_id, sticker_id=sticker.id).first():
            db.session.add(UserSticker(user_id=friend_id, sticker_id=sticker.id))
    db.session.commit()
    socketio.emit("sticker_pack_shared", {
        "sender_id": uid,
        "stickers": [{"id": item.id, "name": item.name, "keywords": item.keywords,
                      "value": item.value, "type": item.sticker_type,
                      "pack": item.pack, "owner_id": item.owner_id} for item in stickers],
    }, to=room(uid, friend_id))
    return jsonify(ok=True, count=len(stickers))


@app.route("/chat/<int:fid>/theme", methods=["POST"])
def update_chat_theme(fid):
    if "user_id" not in session:
        return jsonify(ok=False, error="Login required"), 401
    uid = session["user_id"]
    if not (can_message(uid, fid) or can_message(fid, uid)):
        return jsonify(ok=False, error="Chat unavailable"), 403

    data = request.get_json(silent=True) or request.form
    theme_name = data.get("theme")
    if theme_name not in CHAT_THEMES:
        return jsonify(ok=False, error="Unknown theme"), 400

    preference = ChatPreference.query.filter_by(user_id=uid, friend_id=fid).first()
    if preference is None:
        preference = ChatPreference(user_id=uid, friend_id=fid)
        db.session.add(preference)
    preference.theme = theme_name
    db.session.commit()
    return jsonify(ok=True, theme=theme_name)


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
        join_room(f"user_{uid}")
        sessions = online_sessions.setdefault(uid, set())
        was_offline = not sessions
        sessions.add(request.sid)
        if was_offline:
            user = db.session.get(User, uid)
            if user and user.show_online_status is not False:
                emit("user_status", {"user_id": uid, "status": "online"}, broadcast=True)
            else:
                emit("user_status", {
                    "user_id": uid, "status": "offline",
                    "last_active_at": user.last_active_at.isoformat() + "Z" if user and user.last_active_at and user.show_last_seen is not False else "",
                }, broadcast=True)


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
                "last_active_at": last_active.isoformat() + "Z" if user and user.show_last_seen is not False else "",
            }, broadcast=True)


@socketio.on("join")
def on_join(data):
    uid = socket_user()
    fid = peer_id(data)
    if uid is None or not (can_message(uid, fid) or can_message(fid, uid)):
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
        reader = db.session.get(User, uid)
        seen_message_ids = []
        read_message_ids = []
        for message in unread:
            if message.delete_after_seen:
                seen_message_ids.append(message.id)
                db.session.delete(message)
            else:
                message.delivered_at = message.delivered_at or now
                message.read_at = now
                message.read_receipt_hidden = reader.show_read_receipts is False if reader else False
                if not message.read_receipt_hidden:
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

    slot_reserved, remaining = reserve_pending_message_slot(uid, fid)
    if not slot_reserved:
        emit_pending_message_status(uid, fid)
        return

    # sender_id comes from the session, so a client cannot impersonate.
    sender = db.session.get(User, uid)
    retention = sender.message_retention if sender else "off"
    now = utcnow()
    recipient_is_viewing = bool(
        chat_room_viewers.get(room(uid, fid), {}).get(fid)
    )
    recipient = db.session.get(User, fid)
    msg = Message(
        sender_id=uid,
        receiver_id=fid,
        content=content[:MAX_MESSAGE_LEN],
        message_type="text",
        timestamp=now,
        expires_at=message_expiry(retention, now),
        delete_after_seen=retention == "seen",
        read_receipt_hidden=bool(recipient_is_viewing and recipient and recipient.show_read_receipts is False),
    )
    if recipient_is_viewing:
        msg.delivered_at = now
        msg.read_at = msg.delivered_at

    db.session.add(msg)
    db.session.commit()
    if remaining is not None:
        emit_pending_message_status(uid, fid)

    emit("receive_message", {
        "id": msg.id,
        "content": msg.content,
        "message_type": msg.message_type or "text",
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "time": msg.timestamp.strftime("%H:%M"),
        "receipt": "seen" if msg.read_at and not msg.read_receipt_hidden else ("delivered" if msg.delivered_at else "sent"),
        "expires_at": msg.expires_at.isoformat() if msg.expires_at else None,
    }, room=room(uid, fid))
    notify_inbox(fid, {"sender_id": uid, "receiver_id": fid,
                       "content": msg.content, "message_type": msg.message_type or "text"})
    if recipient_is_viewing and retention == "seen":
        db.session.delete(msg)
        db.session.commit()
        emit("message_deleted", {"id": msg.id}, room=room(uid, fid))


@socketio.on("send_sticker")
def handle_send_sticker(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return
    try:
        sticker_id = int(data.get("sticker_id"))
    except (TypeError, ValueError, AttributeError):
        return
    sticker = db.session.get(Sticker, sticker_id)
    if not sticker or sticker.is_active is False:
        return
    if sticker.owner_id is not None and sticker.owner_id != uid and not StickerShare.query.filter_by(
        sticker_id=sticker_id, user_id=uid
    ).first():
        return

    slot_reserved, remaining = reserve_pending_message_slot(uid, fid)
    if not slot_reserved:
        emit_pending_message_status(uid, fid)
        return

    now = utcnow()
    sender = db.session.get(User, uid)
    recipient = db.session.get(User, fid)
    retention = sender.message_retention if sender else "off"
    room_name = room(uid, fid)
    recipient_is_viewing = bool(chat_room_viewers.get(room_name, {}).get(fid))
    message = Message(sender_id=uid, receiver_id=fid, content=str(sticker.id),
                      message_type="sticker", timestamp=now,
                      expires_at=message_expiry(retention, now),
                      delete_after_seen=retention == "seen",
                      read_receipt_hidden=bool(recipient_is_viewing and recipient and recipient.show_read_receipts is False))
    if recipient_is_viewing:
        message.delivered_at = now
        message.read_at = now
    preference = UserSticker.query.filter_by(user_id=uid, sticker_id=sticker_id).first()
    if preference is None:
        preference = UserSticker(user_id=uid, sticker_id=sticker_id)
        db.session.add(preference)
    preference.recent_at = now
    recipient_preference = UserSticker.query.filter_by(user_id=fid, sticker_id=sticker_id).first()
    if recipient_preference is None:
        recipient_preference = UserSticker(user_id=fid, sticker_id=sticker_id)
        db.session.add(recipient_preference)
    recipient_preference.recent_at = now
    if sticker.owner_id is not None and not StickerShare.query.filter_by(sticker_id=sticker_id, user_id=fid).first():
        db.session.add(StickerShare(sticker_id=sticker_id, user_id=fid))
    db.session.add(message)
    db.session.commit()
    if remaining is not None:
        emit_pending_message_status(uid, fid)
    payload = {"id": message.id, "content": message.content, "message_type": "sticker",
               "sender_id": uid, "receiver_id": fid, "time": now.strftime("%H:%M"),
               "receipt": "seen" if message.read_at and not message.read_receipt_hidden else ("delivered" if message.delivered_at else "sent"),
               "sticker": {"id": sticker.id, "name": sticker.name, "keywords": sticker.keywords,
                           "value": sticker.value, "type": sticker.sticker_type,
                           "pack": sticker.pack, "owner_id": sticker.owner_id}}
    emit("receive_message", payload, room=room_name)
    notify_inbox(fid, {"sender_id": uid, "receiver_id": fid,
                       "content": sticker.name, "message_type": "sticker"})
    if recipient_is_viewing and retention == "seen":
        db.session.delete(message)
        db.session.commit()
        emit("message_deleted", {"id": message.id}, room=room_name)


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
    if msg is None or msg.message_type == "sticker" or not content:
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
    if not can_message(uid, target_id):
        return {"ok": False}

    source = Message.query.filter_by(id=message_id).filter(
        ((Message.sender_id == uid) & (Message.receiver_id == source_friend_id)) |
        ((Message.sender_id == source_friend_id) & (Message.receiver_id == uid))
    ).first()
    if source is None:
        return {"ok": False}

    slot_reserved, remaining = reserve_pending_message_slot(uid, target_id)
    if not slot_reserved:
        emit_pending_message_status(uid, target_id)
        target = db.session.get(User, target_id)
        return {"ok": False, "error": "message_limit",
                "recipient_name": target.username if target else "your friend"}

    target_room = room(uid, target_id)
    target_is_viewing = bool(chat_room_viewers.get(target_room, {}).get(target_id))
    sender = db.session.get(User, uid)
    recipient = db.session.get(User, target_id)
    retention = sender.message_retention if sender else "off"
    now = utcnow()
    forwarded_sticker = db.session.get(Sticker, int(source.content)) if source.message_type == "sticker" and source.content.isdigit() else None
    if source.message_type == "sticker" and (not forwarded_sticker or forwarded_sticker.is_active is False):
        return {"ok": False}
    forwarded = Message(
        sender_id=uid,
        receiver_id=target_id,
        content=source.content if source.message_type == "sticker" else ("↪ Forwarded: " + source.content)[:MAX_MESSAGE_LEN],
        message_type=source.message_type or "text",
        timestamp=now,
        expires_at=message_expiry(retention, now),
        delete_after_seen=retention == "seen",
        read_receipt_hidden=bool(target_is_viewing and recipient and recipient.show_read_receipts is False),
    )
    if target_is_viewing:
        forwarded.delivered_at = now
        forwarded.read_at = forwarded.delivered_at
    if forwarded_sticker:
        target_preference = UserSticker.query.filter_by(user_id=target_id, sticker_id=forwarded_sticker.id).first()
        if target_preference is None:
            target_preference = UserSticker(user_id=target_id, sticker_id=forwarded_sticker.id)
            db.session.add(target_preference)
        target_preference.recent_at = now
        if forwarded_sticker.owner_id is not None and not StickerShare.query.filter_by(
            sticker_id=forwarded_sticker.id, user_id=target_id
        ).first():
            db.session.add(StickerShare(sticker_id=forwarded_sticker.id, user_id=target_id))
    db.session.add(forwarded)
    db.session.commit()
    if remaining is not None:
        emit_pending_message_status(uid, target_id)

    payload = {
        "id": forwarded.id,
        "content": forwarded.content,
        "sender_id": uid,
        "receiver_id": target_id,
        "time": forwarded.timestamp.strftime("%H:%M"),
        "receipt": "seen" if forwarded.read_at and not forwarded.read_receipt_hidden else ("delivered" if forwarded.delivered_at else "sent"),
        "expires_at": forwarded.expires_at.isoformat() if forwarded.expires_at else None,
    }
    if forwarded_sticker:
        payload["sticker"] = {"id": forwarded_sticker.id, "name": forwarded_sticker.name,
                              "keywords": forwarded_sticker.keywords, "value": forwarded_sticker.value,
                              "type": forwarded_sticker.sticker_type, "pack": forwarded_sticker.pack,
                              "owner_id": forwarded_sticker.owner_id}
    emit("receive_message", payload, room=target_room)
    notify_inbox(target_id, {"sender_id": uid, "receiver_id": target_id,
                             "content": forwarded.content, "message_type": forwarded.message_type or "text"})
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
