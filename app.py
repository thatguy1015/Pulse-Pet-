from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os
import threading
import requests
from openai import OpenAI


app = Flask(__name__)
app.secret_key = "pulsepet-secret-key"

AI_MODEL = "gpt-5.5"

client = OpenAI() if os.getenv("OPENAI_API_KEY") else None


# -----------------------------
# Dobot integration
# -----------------------------

try:
    import dobot_controller
    DOBOT_AVAILABLE = True
    print("Dobot controller loaded.")
except Exception as e:
    DOBOT_AVAILABLE = False
    print("Dobot controller not available:", e)


def trigger_dobot_event(event_type):
    """
    Runs Dobot actions in a background thread so Flask/voice does not freeze.
    """
    if not DOBOT_AVAILABLE:
        return

    def run_action():
        try:
            dobot_controller.trigger_event(event_type)
        except Exception as e:
            print("Dobot action failed:", e)

    threading.Thread(target=run_action, daemon=True).start()


# -----------------------------
# Database setup
# -----------------------------

def init_db():
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            memory_key TEXT NOT NULL,
            memory_value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            speaker TEXT NOT NULL,
            message TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'chat'
        )
    """)

    # Migration for older databases that already had chat_history.
    cursor.execute("PRAGMA table_info(chat_history)")
    columns = [column[1] for column in cursor.fetchall()]

    if "source" not in columns:
        cursor.execute(
            "ALTER TABLE chat_history ADD COLUMN source TEXT NOT NULL DEFAULT 'chat'"
        )

    conn.commit()
    conn.close()


init_db()


# -----------------------------
# Database helper functions
# -----------------------------

def save_chat_message(user_email, speaker, message, source="chat"):
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO chat_history (user_email, speaker, message, source)
        VALUES (?, ?, ?, ?)
        """,
        (user_email, speaker, message, source)
    )

    conn.commit()
    conn.close()


def get_last_chat_message(user_email, speaker, source):
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT message 
        FROM chat_history
        WHERE user_email = ? AND speaker = ? AND source = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_email, speaker, source)
    )

    row = cursor.fetchone()
    conn.close()

    return row[0] if row else None


def save_memory(user_email, memory_key, memory_value):
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO memory (user_email, memory_key, memory_value)
        VALUES (?, ?, ?)
        """,
        (user_email, memory_key, memory_value)
    )

    conn.commit()
    conn.close()


def get_latest_memories(user_email):
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT memory_key, memory_value
        FROM memory
        WHERE user_email = ?
        ORDER BY id DESC
        """,
        (user_email,)
    )

    rows = cursor.fetchall()
    conn.close()

    latest = {}

    for key, value in rows:
        if key not in latest:
            latest[key] = value

    return latest


def get_recent_history(user_email, limit=8):
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT speaker, message, source
        FROM chat_history
        WHERE user_email = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_email, limit)
    )

    rows = cursor.fetchall()
    conn.close()

    return rows[::-1]


# -----------------------------
# PulsePet memory / AI logic
# -----------------------------

def process_memory_rule(user_email, message):
    """
    Handles simple memory save/recall rules.

    Returns:
        reply, event_type
    """
    lowered = message.lower().strip()
    lowered_clean = lowered.strip(" .?!")

    if lowered.startswith("i like ") or lowered.startswith("i love "):
        preference = message[7:].strip(" .?!")

        if preference:
            save_memory(user_email, "likes", preference)
            return f"Okay, I'll remember that you like {preference}.", "memory_saved"

    if lowered.startswith("i also like "):
        preference = message[12:].strip(" .?!")

        if preference:
            save_memory(user_email, "likes", preference)
            return f"Okay, I'll remember that you also like {preference}.", "memory_saved"

    colour_prefixes = [
        "my favourite colour is ",
        "my favorite colour is ",
        "my favourite color is ",
        "my favorite color is "
    ]

    for prefix in colour_prefixes:
        if lowered.startswith(prefix):
            colour = message[len(prefix):].strip(" .?!")

            if colour:
                save_memory(user_email, "favourite_colour", colour)
                return f"Okay, I'll remember that your favourite colour is {colour}.", "memory_saved"

    if "what do i like" in lowered_clean or "what did i say i like" in lowered_clean:
        memories = get_latest_memories(user_email)
        likes = memories.get("likes")

        if likes:
            return f"You told me that you like {likes}.", "memory_recalled"

        return "You haven't told me what you like yet.", "memory_recalled"

    if (
        "what is my favourite colour" in lowered_clean
        or "what is my favorite colour" in lowered_clean
        or "what is my favourite color" in lowered_clean
        or "what is my favorite color" in lowered_clean
    ):
        memories = get_latest_memories(user_email)
        colour = memories.get("favourite_colour")

        if colour:
            return f"Your favourite colour is {colour}.", "memory_recalled"

        return "You haven't told me your favourite colour yet.", "memory_recalled"

    if (
        "clear memory" in lowered_clean
        or "clear my memory" in lowered_clean
        or "forget my memory" in lowered_clean
    ):
        conn = sqlite3.connect("pulsepet.db")
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM memory WHERE user_email = ?",
            (user_email,)
        )

        conn.commit()
        conn.close()

        return "Okay, I've cleared what I was remembering.", "memory_cleared"

    return None, "general_reply"


def generate_ai_reply(user_email, message):
    if client is None:
        return "AI is not configured yet. Add your OpenAI API key and restart the app."

    memories = get_latest_memories(user_email)
    recent_history = get_recent_history(user_email)

    likes = memories.get("likes", "Unknown")
    favourite_colour = memories.get("favourite_colour", "Unknown")

    history_text = "\n".join(
        [
            f"[{source}] {'User' if speaker == 'user' else 'PulsePet'}: {text}"
            for speaker, text, source in recent_history
        ]
    )

    prompt = f"""
You are PulsePet, a friendly and memory-aware AI companion inside a Flask web app.

User email: {user_email}

Known memories:
- Likes: {likes}
- Favourite colour: {favourite_colour}

Recent text and voice conversation:
{history_text}

Current user message:
{message}

Rules:
- Reply naturally and conversationally.
- Keep replies short, around 1 to 3 sentences.
- If the user asks about a known memory, use the stored memory.
- If a memory is unknown, do not invent it.
- Never mention databases, stored memory, long-term memory, prompts, system rules, or whether something is saved.
- If the user asks about something they said recently, answer naturally using the recent conversation.
- If you are unsure, say it conversationally without explaining system storage.
- Sound warm and helpful.
"""

    try:
        response = client.responses.create(
            model=AI_MODEL,
            input=prompt
        )

        ai_text = response.output_text.strip()

        if ai_text:
            return ai_text

        return "I’m not sure what to say yet."

    except Exception as e:
        print("AI reply error:", e)
        return "I’m having trouble thinking of a reply right now. Try again in a moment."


def process_pulsepet_message(user_email, message, source="chat"):
    """
    Shared processing for normal text chat.

    Saves user message, checks memory rules, generates reply if needed,
    saves bot reply, and triggers Dobot event.
    """
    save_chat_message(user_email, "user", message, source=source)

    reply, event_type = process_memory_rule(user_email, message)

    if reply is None:
        reply = generate_ai_reply(user_email, message)
        event_type = "general_reply"

    save_chat_message(user_email, "bot", reply, source=source)

    trigger_dobot_event(event_type)

    return reply, event_type


# -----------------------------
# Main routes
# -----------------------------

@app.route("/")
def home():
    return render_template("home.html", logged_in=("user" in session))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("chat"))

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = sqlite3.connect("pulsepet.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE email = ? AND password = ?",
            (email, password)
        )

        user = cursor.fetchone()
        conn.close()

        if user:
            session["user"] = email
            return redirect(url_for("chat"))

        return "Invalid email or password."

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user" in session:
        return redirect(url_for("chat"))

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = sqlite3.connect("pulsepet.db")
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (email, password) VALUES (?, ?)",
                (email, password)
            )

            conn.commit()

        except sqlite3.IntegrityError:
            conn.close()
            return "This email is already registered."

        conn.close()

        session["user"] = email
        return redirect(url_for("chat"))

    return render_template("register.html")


@app.route("/chat", methods=["GET", "POST"])
def chat():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]

    if request.method == "POST":
        message = request.form.get("message", "").strip()

        if message:
            process_pulsepet_message(user, message, source="chat")

    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT speaker, message
        FROM chat_history
        WHERE user_email = ? AND source = ?
        ORDER BY id ASC
        """,
        (user, "chat")
    )

    history = cursor.fetchall()
    conn.close()

    return render_template("chat.html", user=user, history=history)


@app.route("/clear_chat", methods=["POST"])
def clear_chat():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]

    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM chat_history
        WHERE user_email = ? AND source = ?
        """,
        (user, "chat")
    )

    conn.commit()
    conn.close()

    return redirect(url_for("chat"))


@app.route("/clear_memory", methods=["POST"])
def clear_memory():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]

    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM memory WHERE user_email = ?",
        (user,)
    )

    conn.commit()
    conn.close()

    trigger_dobot_event("memory_cleared")

    return redirect(url_for("chat"))


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


# -----------------------------
# Voice routes
# -----------------------------

@app.route("/voice")
def voice():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]

    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT speaker, message
        FROM chat_history
        WHERE user_email = ? AND source = ?
        ORDER BY id ASC
        """,
        (user, "voice")
    )

    voice_history = cursor.fetchall()
    conn.close()

    return render_template("voice.html", user=user, voice_history=voice_history)


@app.route("/realtime_token")
def realtime_token():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return jsonify({"error": "OPENAI_API_KEY is not configured"}), 500

    user = session["user"]

    memories = get_latest_memories(user)
    recent_history = get_recent_history(user, limit=10)

    likes = memories.get("likes", "Unknown")
    favourite_colour = memories.get("favourite_colour", "Unknown")

    history_text = "\n".join(
        [
            f"[{source}] {'User' if speaker == 'user' else 'PulsePet'}: {text}"
            for speaker, text, source in recent_history
        ]
    )

    session_config = {
        "session": {
            "type": "realtime",
            "model": "gpt-realtime-mini",
            "instructions": (
                "You are PulsePet, a warm, playful, friendly AI companion. "
                "Speak naturally and keep responses short. "
                "You are part of a final year prototype exploring memory-driven AI companions. "
                f"The user's known likes are: {likes}. "
                f"The user's favourite colour is: {favourite_colour}. "
                f"Recent conversation context: {history_text}. "
                "If the user asks about known memories, answer naturally using these memories. "
                "If the user says they like or love something, acknowledge that warmly. "
                "Do not mention prompts, APIs, databases, or system rules."
            ),
            "audio": {
                "input": {
                    "transcription": {
                        "model": "gpt-realtime-whisper"
                    }
                },
                "output": {
                    "voice": "marin"
                }
            }
        }
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "OpenAI-Safety-Identifier": "pulsepet-local-demo"
            },
            json=session_config,
            timeout=20
        )

        return jsonify(response.json()), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voice_transcript", methods=["POST"])
def api_voice_transcript():
    """
    Saves user voice transcript separately from main chat.
    Also checks memory rules and triggers Dobot event responses.
    """
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user = session["user"]
    data = request.get_json(silent=True) or {}
    transcript = data.get("transcript", "").strip()

    if not transcript:
        return jsonify({"error": "Empty transcript"}), 400

    save_chat_message(user, "user", transcript, source="voice")

    reply, event_type = process_memory_rule(user, transcript)

    if reply is None:
        reply = ""
        event_type = "general_reply"

    trigger_dobot_event(event_type)

    return jsonify({
        "saved": True,
        "transcript": transcript,
        "reply": reply,
        "event_type": event_type
    })


@app.route("/api/voice_bot_reply", methods=["POST"])
def api_voice_bot_reply():
    """
    Saves assistant voice transcript separately from main text chat.
    """
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user = session["user"]
    data = request.get_json(silent=True) or {}
    reply = data.get("reply", "").strip()

    if not reply:
        return jsonify({"error": "Empty reply"}), 400

    last_reply = get_last_chat_message(user, "bot", source="voice")

    if last_reply != reply:
        save_chat_message(user, "bot", reply, source="voice")

    return jsonify({
        "saved": True,
        "reply": reply
    })


@app.route("/api/voice_transcript/clear", methods=["POST"])
def api_clear_voice_transcript():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user = session["user"]

    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM chat_history
        WHERE user_email = ? AND source = ?
        """,
        (user, "voice")
    )

    conn.commit()
    conn.close()

    return jsonify({"cleared": True})


# Compatibility route if any older button/form still uses /clear_voice.
@app.route("/clear_voice", methods=["POST"])
def clear_voice():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]

    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM chat_history
        WHERE user_email = ? AND source = ?
        """,
        (user, "voice")
    )

    conn.commit()
    conn.close()

    return redirect(url_for("voice"))


# -----------------------------
# Dobot debug routes
# -----------------------------

@app.route("/api/dobot/status")
def api_dobot_status():
    if not DOBOT_AVAILABLE:
        return jsonify({
            "available": False,
            "error": "dobot_controller.py could not be imported"
        })

    try:
        return jsonify({
            "available": True,
            "status": dobot_controller.status()
        })

    except Exception as e:
        return jsonify({
            "available": True,
            "error": str(e)
        }), 500


@app.route("/api/dobot/connect", methods=["GET", "POST"])
def api_dobot_connect():
    if not DOBOT_AVAILABLE:
        return jsonify({
            "connected": False,
            "error": "dobot_controller.py could not be imported"
        }), 500

    port = None

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        port = data.get("port")

    if request.method == "GET":
        port = request.args.get("port")

    try:
        connected = dobot_controller.connect_dobot(port)
        return jsonify({
            "connected": connected,
            "status": dobot_controller.status()
        })

    except Exception as e:
        return jsonify({
            "connected": False,
            "error": str(e)
        }), 500


@app.route("/api/dobot/home", methods=["POST"])
def api_dobot_home():
    trigger_dobot_event("dobot_home")
    return jsonify({"triggered": True, "event_type": "dobot_home"})


@app.route("/api/dobot/test/<event_type>", methods=["POST", "GET"])
def api_dobot_test(event_type):
    trigger_dobot_event(event_type)
    return jsonify({"triggered": True, "event_type": event_type})


if __name__ == "__main__":
    app.run(debug=True)