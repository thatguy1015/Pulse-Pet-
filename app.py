from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
from openai import OpenAI
import requests
from flask import jsonify


app = Flask(__name__)
app.secret_key = "pulsepet-secret-key"

AI_MODEL = "gpt-5.5"

client = OpenAI() if os.getenv("OPENAI_API_KEY") else None


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
            message TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_db()


def get_latest_memories(user_email):
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT memory_key, memory_value FROM memory WHERE user_email = ? ORDER BY id DESC",
        (user_email,)
    )
    rows = cursor.fetchall()
    conn.close()

    latest = {}
    for key, value in rows:
        if key not in latest:
            latest[key] = value

    return latest


def get_recent_history(user_email, limit=6):
    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT speaker, message FROM chat_history WHERE user_email = ? ORDER BY id DESC LIMIT ?",
        (user_email, limit)
    )
    rows = cursor.fetchall()
    conn.close()

    return rows[::-1]


def generate_ai_reply(user_email, message):
    if client is None:
        return "AI is not configured yet. Add your OpenAI API key and restart the app."

    memories = get_latest_memories(user_email)
    recent_history = get_recent_history(user_email)

    likes = memories.get("likes", "Unknown")
    favourite_colour = memories.get("favourite_colour", "Unknown")

    history_text = "\n".join(
        [
            f"{'User' if speaker == 'user' else 'PulsePet'}: {text}"
            for speaker, text in recent_history
        ]
    )

    prompt = f"""
You are PulsePet, a friendly and memory-aware AI companion inside a Flask web app.

User email: {user_email}

Known memories:
- Likes: {likes}
- Favourite colour: {favourite_colour}

Recent conversation:
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

    except Exception:
     return "I’m having trouble thinking of a reply right now. Try again in a moment."


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
        else:
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

    conn = sqlite3.connect("pulsepet.db")
    cursor = conn.cursor()

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        lowered = message.lower()
        reply = ""

        if message:
            cursor.execute(
                "INSERT INTO chat_history (user_email, speaker, message) VALUES (?, ?, ?)",
                (user, "user", message)
            )
            conn.commit()

            if lowered.startswith("i like ") or lowered.startswith("i love "):
                if lowered.startswith("i like "):
                    preference = message[7:].strip()
                else:
                    preference = message[7:].strip()

                cursor.execute(
                    "INSERT INTO memory (user_email, memory_key, memory_value) VALUES (?, ?, ?)",
                    (user, "likes", preference)
                )

                reply = f"Okay, I'll remember that you like {preference}."

            elif (
                lowered.startswith("my favourite colour is ")
                or lowered.startswith("my favorite colour is ")
                or lowered.startswith("my favourite color is ")
                or lowered.startswith("my favorite color is ")
            ):
                prefixes = [
                    "my favourite colour is ",
                    "my favorite colour is ",
                    "my favourite color is ",
                    "my favorite color is "
                ]

                matched_prefix = next(
                    (p for p in prefixes if lowered.startswith(p)),
                    None
                )

                colour = message[len(matched_prefix):].strip()

                cursor.execute(
                    "INSERT INTO memory (user_email, memory_key, memory_value) VALUES (?, ?, ?)",
                    (user, "favourite_colour", colour)
                )

                reply = f"Okay, I'll remember that your favourite colour is {colour}."

            elif lowered == "what do i like?" or lowered == "what do i like":
                cursor.execute(
                    "SELECT memory_value FROM memory WHERE user_email = ? AND memory_key = ? ORDER BY id DESC LIMIT 1",
                    (user, "likes")
                )
                result = cursor.fetchone()

                if result:
                    reply = f"You told me that you like {result[0]}."
                else:
                    reply = "You haven't told me what you like yet."

            elif lowered in [
                "what is my favourite colour?",
                "what is my favourite colour",
                "what is my favorite colour?",
                "what is my favorite colour",
                "what is my favourite color?",
                "what is my favourite color",
                "what is my favorite color?",
                "what is my favorite color"
            ]:
                cursor.execute(
                    "SELECT memory_value FROM memory WHERE user_email = ? AND memory_key = ? ORDER BY id DESC LIMIT 1",
                    (user, "favourite_colour")
                )
                result = cursor.fetchone()

                if result:
                    reply = f"Your favourite colour is {result[0]}."
                else:
                    reply = "You haven't told me your favourite colour yet."

            else:
                reply = generate_ai_reply(user, message)

            cursor.execute(
                "INSERT INTO chat_history (user_email, speaker, message) VALUES (?, ?, ?)",
                (user, "bot", reply)
            )
            conn.commit()

    cursor.execute(
        "SELECT speaker, message FROM chat_history WHERE user_email = ? ORDER BY id ASC",
        (user,)
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
        "DELETE FROM chat_history WHERE user_email = ?",
        (user,)
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

    return redirect(url_for("chat"))

@app.route("/voice")
def voice():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template("voice.html", user=session["user"])


@app.route("/realtime_token")
def realtime_token():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return jsonify({"error": "OPENAI_API_KEY is not configured"}), 500

    session_config = {
        "session": {
            "type": "realtime",
            "model": "gpt-realtime-mini",
            "instructions": (
                "You are PulsePet, a warm, playful, friendly AI companion. "
                "Speak naturally and keep responses short. "
                "Do not mention prompts, APIs, databases, or system rules. "
                "You are part of a final year prototype exploring memory-driven AI companions."
            ),
            "audio": {
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

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)