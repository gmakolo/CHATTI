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

@app.route("/")
def home():
    if "user_id" in session:
        return "Welcome to CHATTI! <a href='/friends'>Friends</a> | <a href='/logout'>Log out</a>"
    return redirect("/login")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not username:
            flash("Username can't be empty or just spaces.", "error")
            return redirect("/signup")

        if not re.match(r'^[A-Za-z!@#$%^&*()_+\-=\[\]{};:,.<>?]+$', username):
            flash("Username can only contain letters and symbols (no numbers).", "error")
            return redirect("/signup")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return redirect("/signup")

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("That username is already taken.", "error")
            return redirect("/signup")

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash("Account created! You can log in now.", "success")
        return redirect("/login")
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            return redirect("/")
        flash("Invalid username or password.", "error")
        return redirect("/login")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect("/login")

def get_friend_ids(user_id):
    sent = Friendship.query.filter_by(user_id=user_id).all()
    received = Friendship.query.filter_by(friend_id=user_id).all()
    friend_ids = [f.friend_id for f in sent] + [f.user_id for f in received]
    return friend_ids

@app.route("/friends", methods=["GET"])
def friends():
    if "user_id" not in session:
        return redirect("/login")

    current_user_id = session["user_id"]
    friend_ids = get_friend_ids(current_user_id)
    friend_list = User.query.filter(User.id.in_(friend_ids)).all()

    search_query = request.args.get("search")
    search_results = []
    if search_query:
        search_results = User.query.filter(
            User.username.contains(search_query),
            User.id != current_user_id
        ).all()

    return render_template("friends.html", friends=friend_list, search_results=search_results)

@app.route("/add_friend/<int:friend_id>", methods=["POST"])
def add_friend(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    current_user_id = session["user_id"]
    existing = Friendship.query.filter_by(user_id=current_user_id, friend_id=friend_id).first()
    if not existing:
        new_friendship = Friendship(user_id=current_user_id, friend_id=friend_id)
        db.session.add(new_friendship)
        db.session.commit()
    return redirect("/friends")

@app.route("/unfriend/<int:friend_id>", methods=["POST"])
def unfriend(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    current_user_id = session["user_id"]
    Friendship.query.filter_by(user_id=current_user_id, friend_id=friend_id).delete()
    Friendship.query.filter_by(user_id=friend_id, friend_id=current_user_id).delete()
    db.session.commit()
    return redirect("/friends")

def get_messages_between(user_a, user_b):
    return Message.query.filter(
        ((Message.sender_id == user_a) & (Message.receiver_id == user_b)) |
        ((Message.sender_id == user_b) & (Message.receiver_id == user_a))
    ).order_by(Message.id).all()

@app.route("/chat/<int:friend_id>")
def chat(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    current_user_id = session["user_id"]
    friend = User.query.get(friend_id)
    messages = get_messages_between(current_user_id, friend_id)

    return render_template("chat.html", friend=friend, messages=messages, current_user_id=current_user_id)

@app.route("/messages/<int:friend_id>")
def get_messages_json(friend_id):
    if "user_id" not in session:
        return jsonify([])

    current_user_id = session["user_id"]
    messages = get_messages_between(current_user_id, friend_id)

    result = []
    for m in messages:
        result.append({
            "content": m.content,
            "is_mine": m.sender_id == current_user_id,
            "time": m.timestamp.strftime("%I:%M %p") if m.timestamp else ""
        })
    return jsonify(result)
@app.route("/")
def home():
    if "user_id" in session:
        return render_template("home.html")
    return redirect("/login")
@app.route("/send_message/<int:friend_id>", methods=["POST"])
def send_message(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    current_user_id = session["user_id"]
    content = request.form["content"]

    new_message = Message(sender_id=current_user_id, receiver_id=friend_id, content=content)
    db.session.add(new_message)
    db.session.commit()

    return redirect(f"/chat/{friend_id}")

if __name__ == "__main__":
    app.run(debug=True)