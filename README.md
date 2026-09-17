# CHATTI

A small real-time chat app built with Flask, Flask-SocketIO and SQLite.
Sign up, add friends by username, then chat with them live over WebSockets.

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

1. Go to `/signup` and create an account.
2. Log in.
3. On the **Friends** page, type another user's username and add them.
   (Friendships are one-way rows but work in both directions once added.)
4. Click a friend to open the chat and send messages.

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

Both are convenience wrappers — the app already does this on import.

To start over with a clean database, delete `instance/chatti.db` and restart.
This deletes all users and messages.

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
