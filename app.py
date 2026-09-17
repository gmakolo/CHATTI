import os
import re
from flask import Flask, render_template, request, redirect, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chatti.db"
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-fallback-key")
db = SQLAlchemy(app)

# MODELS
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# HOME (FIXED SINGLE VERSION)
@app.route("/")
def home():
    if "user_id" in session:
        return render_template("home.html")
    return redirect("/login")

# SIGNUP
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not username:
            flash("Username cannot be empty", "error")
            return redirect("/signup")

        # FIXED: allows letters + numbers (normal usernames)
        if not re.match(r'^[A-Za-z0-9_]+$', username):
            flash("Username can only contain letters, numbers, underscore", "error")
            return redirect("/signup")

        if len(password) < 6:
            flash("Password must be at least 6 characters", "error")
            return redirect("/signup")

        if User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
            return redirect("/signup")

        user = User(username=username, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        flash("Account created!", "success")
        return redirect("/login")

    return render_template("signup.html")

# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            return redirect("/")
        flash("Invalid login", "error")
        return redirect("/login")

    return render_template("login.html")

# LOGOUT
@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect("/login")

# FRIENDS HELPERS
def get_friend_ids(user_id):
    sent = Friendship.query.filter_by(user_id=user_id).all()
    received = Friendship.query.filter_by(friend_id=user_id).all()
    return [f.friend_id for f in sent] + [f.user_id for f in received]

# FRIENDS PAGE
@app.route("/friends")
def friends():
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    friend_ids = get_friend_ids(uid)

    friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []

    search = request.args.get("search")
    results = []

    if search:
        results = User.query.filter(
            User.username.contains(search),
            User.id != uid
        ).all()

    return render_template("friends.html", friends=friends, search_results=results)

# ADD FRIEND
@app.route("/add_friend/<int:friend_id>", methods=["POST"])
def add_friend(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]

    exists = Friendship.query.filter_by(user_id=uid, friend_id=friend_id).first()
    if not exists:
        db.session.add(Friendship(user_id=uid, friend_id=friend_id))
        db.session.commit()

    return redirect("/friends")

# UNFRIEND
@app.route("/unfriend/<int:friend_id>", methods=["POST"])
def unfriend(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]

    Friendship.query.filter_by(user_id=uid, friend_id=friend_id).delete()
    Friendship.query.filter_by(user_id=friend_id, friend_id=uid).delete()
    db.session.commit()

    return redirect("/friends")

# GET MESSAGES
def get_messages_between(a, b):
    return Message.query.filter(
        ((Message.sender_id == a) & (Message.receiver_id == b)) |
        ((Message.sender_id == b) & (Message.receiver_id == a))
    ).order_by(Message.id).all()

# CHAT PAGE
@app.route("/chat/<int:friend_id>")
def chat(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    uid = session["user_id"]
    friend = User.query.get(friend_id)

    messages = get_messages_between(uid, friend_id)

    return render_template("chat.html", friend=friend, messages=messages)

# SEND MESSAGE
@app.route("/send_message/<int:friend_id>", methods=["POST"])
def send_message(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    content = request.form["content"].strip()

    if not content:
        return redirect(f"/chat/{friend_id}")

    db.session.add(Message(
        sender_id=session["user_id"],
        receiver_id=friend_id,
        content=content
    ))
    db.session.commit()

    return redirect(f"/chat/{friend_id}")

# JSON API
@app.route("/messages/<int:friend_id>")
def get_messages_json(friend_id):
    if "user_id" not in session:
        return jsonify([])

    uid = session["user_id"]
    msgs = get_messages_between(uid, friend_id)

    return jsonify([
        {
            "content": m.content,
            "is_mine": m.sender_id == uid,
            "time": m.timestamp.strftime("%H:%M")
        }
        for m in msgs
    ])

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)