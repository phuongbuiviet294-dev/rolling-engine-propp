import streamlit as st
import requests
import json
from datetime import datetime

# ================= CONFIG ================= #

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxjblHz-kQ_4Bzb-VtO-Ux7_siTTA2-cQ-DGK8apuSxHz3_mDskP0OReynSunKJOmKL/exec"

LOCK_ROUNDS = 18
MIN_WINRATE = 60
WEIGHT_BASE = 1

# ================= DAILY RESET ================= #

today = datetime.now().strftime("%Y-%m-%d")

if "engine_date" not in st.session_state:
    st.session_state.engine_date = today

if "engine_data" not in st.session_state:
    st.session_state.engine_data = []

if "lock_window" not in st.session_state:
    st.session_state.lock_window = None
    st.session_state.lock_remaining = 0

if st.session_state.engine_date != today:
    st.session_state.engine_data = []
    st.session_state.lock_window = None
    st.session_state.lock_remaining = 0
    st.session_state.engine_date = today

# ================= CORE FUNCTIONS ================= #

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

def hits_26(data, w):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    hits = 0
    for i in range(w, len(recent)):
        if recent[i]["group"] == recent[i-w]["group"]:
            hits += 1
    return hits

def streak(data, w):
    s = 0
    i = len(data) - 1
    while i - w >= 0:
        if data[i]["group"] == data[i-w]["group"]:
            s += 1
            i -= 1
        else:
            break
    return s

def volatility_26(data):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    changes = 0
    for i in range(1, len(recent)):
        if recent[i]["group"] != recent[i-1]["group"]:
            changes += 1
    return changes / 25

def break_penalty(data):
    if len(data) < 3:
        return 0
    last3 = [d["hit"] for d in data[-3:]]
    if last3 == [1,0,0] or last3 == [0,1,0]:
        return 2
    return 0

def winrate_26(data):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    hits = [d["hit"] for d in recent if d["hit"] is not None]
    if not hits:
        return 0
    return sum(hits)/len(hits)*100

def scan_best_window(data):
    best_score = 0
    best_w = None

    vol = volatility_26(data)
    weight = 0.8 if vol > 0.6 else 1.0

    for w in range(6, 20):
        h = hits_26(data, w)
        if h < 6:
            continue
        s = streak(data, w)
        if s >= 3:
            penalty = break_penalty(data)
            score = (h * weight) + s - penalty
            if score > best_score:
                best_score = score
                best_w = w

    confidence = min(100, best_score * 5)
    return best_w, confidence

# ================= UI ================= #

st.title("🚀 Rolling Engine PRO++++")
st.caption("Conservative | Lock18 | Vol Filter | Break Penalty | Trade Signal")

input_str = st.text_input("Nhập chuỗi số (vd: 1,4,8,7,2):")

if st.button("RUN") and input_str:

    numbers = [int(x.strip()) for x in input_str.split(",") if x.strip().isdigit()]

    for n in numbers:

        group = get_group(n)
        predicted = None
        hit = None

        # -------- LOCK MODE -------- #

        if st.session_state.lock_window:
            w = st.session_state.lock_window

            if len(st.session_state.engine_data) >= w:
                predicted = st.session_state.engine_data[-w]["group"]
                hit = 1 if predicted == group else 0

            st.session_state.lock_remaining -= 1

            if st.session_state.lock_remaining <= 0:
                st.session_state.lock_window = None

        # -------- SCAN MODE -------- #

        if not st.session_state.lock_window:
            best_w, confidence = scan_best_window(st.session_state.engine_data)
            if best_w:
                st.session_state.lock_window = best_w
                st.session_state.lock_remaining = LOCK_ROUNDS

        record = {
            "round": len(st.session_state.engine_data) + 1,
            "number": n,
            "group": group,
            "predicted": predicted,
            "hit": hit,
            "window": st.session_state.lock_window
        }

        st.session_state.engine_data.append(record)

        # -------- SEND TO GOOGLE SHEET -------- #

        payload = {
            "round": record["round"],
            "number": record["number"],
            "group": record["group"],
            "predicted": record["predicted"],
            "hit": record["hit"],
            "window": record["window"],
            "state": "LOCK" if st.session_state.lock_window else "SCAN"
        }

        try:
            requests.post(WEBHOOK_URL, data=json.dumps(payload), timeout=3)
        except:
            pass

    st.success("Đã xử lý và lưu Google Sheet")

# ================= DASHBOARD ================= #

st.divider()

st.metric("Tổng vòng", len(st.session_state.engine_data))
st.metric("Active Window", st.session_state.lock_window)
st.metric("Lock Remaining", st.session_state.lock_remaining)

vol = volatility_26(st.session_state.engine_data)
wr = winrate_26(st.session_state.engine_data)

st.metric("Volatility 26", round(vol*100,2))
st.metric("Winrate 26", round(wr,2))

if st.session_state.lock_window and wr >= MIN_WINRATE:
    st.success("🚨 TRADE SIGNAL ACTIVE (>=60%)")

if st.button("RESET NOW"):
    st.session_state.engine_data = []
    st.session_state.lock_window = None
    st.session_state.lock_remaining = 0
    st.success("Engine reset (Sheet giữ nguyên)")
