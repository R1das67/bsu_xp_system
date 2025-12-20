import json
import os
import time

DATA_FILE = "data.json"

# -------------------------------------------------
# SAFE LOAD
# -------------------------------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "xp": {},
            "voice_sessions": {},
            "xp_logs": []
        }

    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -------------------------------------------------
# XP FUNCTIONS
# -------------------------------------------------
def get_xp(user_id: int) -> int:
    data = load_data()
    return data["xp"].get(str(user_id), 0)

def add_xp(user_id: int, amount: int, reason: str = "unknown"):
    data = load_data()
    uid = str(user_id)

    old_xp = data["xp"].get(uid, 0)
    new_xp = old_xp + amount
    data["xp"][uid] = new_xp

    # log xp change
    data["xp_logs"].append({
        "user_id": uid,
        "amount": amount,
        "reason": reason,
        "time": int(time.time())
    })

    save_data(data)
    return new_xp

# -------------------------------------------------
# VOICE SESSION HANDLING
# -------------------------------------------------
def start_voice_session(user_id: int):
    data = load_data()
    uid = str(user_id)

    data["voice_sessions"][uid] = {
        "join_time": time.time(),
        "muted_since": None,
        "last_xp": time.time()
    }

    save_data(data)

def end_voice_session(user_id: int):
    data = load_data()
    uid = str(user_id)

    if uid in data["voice_sessions"]:
        del data["voice_sessions"][uid]
        save_data(data)

def update_mute_state(user_id: int, muted: bool):
    data = load_data()
    uid = str(user_id)

    session = data["voice_sessions"].get(uid)
    if not session:
        return

    if muted:
        if session["muted_since"] is None:
            session["muted_since"] = time.time()
    else:
        session["muted_since"] = None

    save_data(data)

# -------------------------------------------------
# XP LOG ACCESS
# -------------------------------------------------
def get_xp_logs():
    data = load_data()
    return data.get("xp_logs", [])
