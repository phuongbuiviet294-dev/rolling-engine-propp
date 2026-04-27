import time
from collections import Counter

import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= REFRESH =================
st_autorefresh(interval=8000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

MODES = [
    {"name": "5v4", "top_windows": 5, "vote_required": 4, "window_min": 6, "window_max": 22},
    {"name": "6v4", "top_windows": 6, "vote_required": 4, "window_min": 6, "window_max": 22},
    {"name": "8v5", "top_windows": 8, "vote_required": 5, "window_min": 6, "window_max": 22},
]

GAP = 1

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PHASE_STOP_WIN = 3.5
PHASE_STOP_LOSS = -2.0

SESSION_STOP_WIN = 20.0
SESSION_STOP_LOSS = -20.0

KEEP_AFTER_LOSS_ROUNDS = 2

# ================= TELEGRAM FIX =================
BOT_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

def telegram_enabled():
    return bool(BOT_TOKEN and CHAT_ID)

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=5)
        return r.ok
    except:
        return False

def send_signal_once(signal_name, current_round, msg):
    if not telegram_enabled():
        return False

    # key unique theo round + signal
    key = f"{signal_name}_{current_round}"

    if "sent_keys" not in st.session_state:
        st.session_state.sent_keys = set()

    if key in st.session_state.sent_keys:
        return False

    ok = send_telegram(msg)

    if ok:
        st.session_state.sent_keys.add(key)

    return ok

# ================= LOAD =================
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

def group_of(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

groups = [group_of(n) for n in numbers]

# ================= SIMPLE ENGINE =================
def simulate_engine():
    profit = 0
    last_trade = -999
    hist = []

    for i in range(10, len(groups)):
        preds = [groups[i-1], groups[i-2], groups[i-3]]
        vote = Counter(preds).most_common(1)[0][0]

        signal = True
        trade = signal and (i - last_trade >= GAP)

        if trade:
            last_trade = i
            if groups[i] == vote:
                profit += WIN_GROUP
                hit = 1
            else:
                profit += LOSS_GROUP
                hit = 0
        else:
            hit = None

        hist.append({
            "round": i,
            "group": groups[i],
            "vote": vote,
            "trade": trade,
            "hit": hit,
            "profit": profit
        })

    return pd.DataFrame(hist), profit

hist, total_profit = simulate_engine()

# ================= NEXT =================
next_round = len(groups)

preds = [groups[-1], groups[-2], groups[-3]]
final_vote = Counter(preds).most_common(1)[0][0]

can_bet = True

# ================= TELEGRAM =================
if can_bet:
    msg = f"""
READY
Round: {next_round}
Next Group: {final_vote}
Profit: {total_profit}
"""
    send_signal_once("READY", next_round, msg)

# ================= UI =================
st.title("ENGINE SIMPLE")

st.metric("Next Group", final_vote)
st.metric("Total Profit", total_profit)

st.dataframe(hist.tail(30))
