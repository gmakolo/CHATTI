# CHATTI

A real-time social messaging app built with Flask, Flask-SocketIO and SQLite.
Sign in with your email address, find friends by username, and chat live over WebSockets.

## Requirements

- **Python 3.10+** (developed and tested on 3.13.5)
- No database server needed — SQLite is used, and the file is created automatically.

## Setup

The `venv/` folder is **not** in version control (see `.gitignore`), so a fresh
clone has no virtual environment. Create one:

```powershell
python -m venv venv
```

Then activate it and install the dependencies.

### Windows — PowerShell

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If PowerShell refuses to run the script with *"running scripts is disabled on
> this system"*, allow it for the current session only:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

### Windows — Command Prompt (cmd)

```cmd
venv\Scripts\activate.bat
pip install -r requirements.txt
```

### macOS / Linux

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Git Bash on Windows

```bash
source venv/Scripts/activate
pip install -r requirements.txt
```

Your prompt changes to `(venv)` once the environment is active.

## Running the app

With the environment active:

```powershell
python app.py
```

Then open the URL it prints — normally **http://127.0.0.1:5000**.

If port 5000 is already taken, the app says so and starts on the next free port
instead, so it never dies on a port clash:

```
Port 5000 is busy -- starting on http://127.0.0.1:5001 instead.
```

To pin a specific port, set `PORT`:

```powershell
$env:PORT = 8080; python app.py     # PowerShell
PORT=8080 python app.py             # macOS / Linux / Git Bash
```

Debug mode is on, so the server reloads automatically when you edit a file.
Stop it with `Ctrl+C`.

## Using it

1. Go to `/signup` and create an account with a unique email address and username.
2. Log in with your email address and password. CHATTI never uses usernames for normal login.
3. On the **People** page, search for a person using the exact email address they
   registered with, then send a friend request. Email search can be turned off in
   Settings, and CHATTI never displays the searched email to other people.
   (Friendships are one-way rows but work in both directions once accepted.)
4. Click an accepted friend to open the chat and send messages.

Older accounts without an email can use **Set up an email for an existing account** on the login page. This one-time form verifies the existing username and password, then attaches a unique email to the same account. It does not create a replacement account or remove messages or friendships. Accounts with no username after login are prompted to choose one before using CHATTI.

## Password recovery

The **Forgot password?** link sends a one-hour reset link to the email address on
the account. Configure an SMTP server and the public app URL before relying on
email recovery. For example, set these environment variables before starting
CHATTI:

```text
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=your-smtp-user
MAIL_PASSWORD=your-smtp-password
MAIL_DEFAULT_SENDER=chatti@example.com
MAIL_USE_TLS=true
MAIL_USE_SSL=false
SECRET_KEY=replace-with-a-long-random-secret
APP_BASE_URL=https://chat.example.com
```

Use your email provider's SMTP host and credentials. Set `SECRET_KEY` to a long,
random value and `APP_BASE_URL` to the
URL users open in their browser so reset links point to the right site. Password
recovery is available through the email address attached to each account.

To try the real-time side yourself, open a second browser (or a private window),
sign up as a second user, add the first user as a friend, and chat between them.
Both windows update live — including the typing indicator and the online dot.

## The database

`instance/chatti.db` is created automatically on first run, and `app.py` brings
its schema up to date on every startup (adding any columns a new model field
needs). So after pulling changes that touch a model, just restart the app.

Two helper scripts exist if you want to see that happen explicitly:

```bash
python init_db.py      # create tables + report the schema
python migrate_db.py   # same, and print every table's columns
```

Both are convenience wrappers — the app already does this on import. Keep
`instance/chatti.db` in place: it contains user accounts, messages, friendships,
posts, and settings. Schema changes are applied without recreating the database.

## Updates and polls

Updates appear in the horizontal story row and expire after 12 hours. A user can
create a poll with a question and two to six distinct options. Friends can vote
once; the creator and people who have voted can see vote totals and percentages.

## People, friendships, and message streaks

The People page separates incoming and outgoing requests, discovery, accepted
friends, and streaks. Friend requests are visible to their two participants;
only the recipient can accept or decline. Accepted friendships persist until a
user removes the friend. Profile owners can hide their accepted-friends and
mutual-friends lists in **Settings → Privacy**. Email search is exact-match and
never returns an email address.

Daily friend streaks use UTC calendar days. A day qualifies after each person in
an accepted friendship sends at least one direct, user-authored message to the
other that day. Repeated messages that day do not add more days. Reactions,
automated notices, and group messages do not count. The streak advances once
when both people complete the next consecutive UTC day. Missing a full day ends
the active streak; the saved historical count remains until the next completed
exchange starts a new streak at one. Refreshes and server restarts do not change
saved streaks. The People page indicates when a streak completed yesterday and
needs messages today to continue.

## Troubleshooting

**`An attempt was made to access a socket in a way forbidden by its access permissions`**

Something else holds port 5000 — on this machine `postgres.exe` does. `python
app.py` now moves to the next free port on its own and prints which one it
picked, so this should not come up. If you see it anyway, something is holding
*every* port the app tried; set `PORT` to a port you know is free.

**`no such column: user.<field>`**

The database predates a model change. Restart the app — the schema is repaired
on startup. If it persists, run `python migrate_db.py`.

**Scary tracebacks with `ConnectionError` in the console**

Harmless. When a WebSocket closes, `simple-websocket` signals the end of the
request by raising `ConnectionError`, and the Werkzeug dev server logs that as a
`500`. The chat itself is unaffected. These disappear under a production server
such as gunicorn, which uses a different code path.

**Messages don't appear live**

Check the browser console for a failed `/socket.io/` request. If
`simple-websocket` is missing the app still works, but Socket.IO falls back to
long-polling instead of WebSockets — re-run `pip install -r requirements.txt`.
