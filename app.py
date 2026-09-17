from flask_socketio import SocketIO, emit, join_room
import os
import socket
from datetime import datetime, timezone

from flask import (
    Flask, render_template, request, redirect, session, flash, abort
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chatti.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")

db = SQLAlchemy(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

MAX_MESSAGE_LEN = 2000

# ======================
# ONLINE USERS
# ======================
online_users = set()


def utcnow():
    """Naive UTC timestamp, without datetime.utcnow()'s 3.12 deprecation."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ======================
# MODELS
# ======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    avatar_url = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
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
    sent = Friendship.query.filter_by(user_id=uid).all()
    recv = Friendship.query.filter_by(friend_id=uid).all()
    return [f.friend_id for f in sent] + [f.user_id for f in recv]


def are_friends(a, b):
    if a is None or b is None or a == b:
        return False

    return (
        Friendship.query.filter_by(user_id=a, friend_id=b).first()
        or Friendship.query.filter_by(user_id=b, friend_id=a).first()
    ) is not None


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
        password = request.form.get("password") or ""

        if not username or not password:
            flash("Username and password are required", "error")
            return redirect("/signup")

        if User.query.filter_by(username=username).first():
            flash("User exists", "error")
            return redirect("/signup")

        db.session.add(User(
            username=username,
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
            return redirect("/friends")

        flash("Invalid login", "error")
        return redirect("/login")

    return render_template("login.html")


@app.route("/logout")
def logout():
    uid = session.get("user_id")
    if uid:
        online_users.discard(uid)

    session.clear()
    return redirect("/login")


@app.route("/friends")
def friends():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    ids = get_friends(uid)

    friends = User.query.filter(User.id.in_(ids)).all() if ids else []

    return render_template(
        "friends.html",
        friends=friends,
        online_users=online_users
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

    if other is None:
        flash("No user with that name", "error")
    elif other.id == uid:
        flash("You cannot add yourself", "error")
    elif are_friends(uid, other.id):
        flash(f"{other.username} is already a friend", "error")
    else:
        db.session.add(Friendship(user_id=uid, friend_id=other.id))
        db.session.commit()
        flash(f"Added {other.username}", "success")

    return redirect("/friends")


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

    messages = Message.query.filter(
        ((Message.sender_id == uid) & (Message.receiver_id == fid)) |
        ((Message.sender_id == fid) & (Message.receiver_id == uid))
    ).order_by(Message.id).all()

    ids = get_friends(uid)
    sidebar = User.query.filter(User.id.in_(ids)).all() if ids else []

    return render_template(
        "chat.html",
        friend=friend,
        friends=sidebar,
        messages=messages,
        current_user_id=uid,
        online_users=online_users,
    )


# ======================
# SOCKET EVENTS
# ======================
@socketio.on("connect")
def on_connect():
    uid = socket_user()
    if uid:
        online_users.add(uid)
        emit("user_status", {"user_id": uid, "status": "online"}, broadcast=True)


@socketio.on("disconnect")
def on_disconnect():
    uid = socket_user()
    if uid:
        online_users.discard(uid)
        emit("user_status", {"user_id": uid, "status": "offline"}, broadcast=True)


@socketio.on("join")
def on_join(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return

    # The room is derived server-side -- never trust a client-supplied name.
    join_room(room(uid, fid))


@socketio.on("send_message")
def handle_send_message(data):
    uid, fid = valid_peer(data)
    if uid is None:
        return

    content = (data.get("content") or "").strip()
    if not content:
        return

    # sender_id comes from the session, so a client cannot impersonate.
    msg = Message(
        sender_id=uid,
        receiver_id=fid,
        content=content[:MAX_MESSAGE_LEN],
    )

    db.session.add(msg)
    db.session.commit()

    emit("receive_message", {
        "content": msg.content,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "time": msg.timestamp.strftime("%H:%M"),
    }, room=room(uid, fid))


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
