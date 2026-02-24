import streamlit as st
import requests
import json
from datetime import datetime

# ================= CONFIG ================= #

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwv6y8wKXsypF3yiZ6gNEWOcqe5wOGWDQWJQNhl1tWrEsLqqtOMcSFBWS-97hwLKED6/exec"
LOCK_ROUNDS = 18

# ================= INIT STATE ================= #

today = datetime.now().strftime("%Y-%m-%d")

if "engine_date" not in st.session_state:
    st.session_state.engine_date = today

if "data" not in st.session_state:
    st.session_state.data = []

if "lock_window" not in st.session_state:
    st.session_state.lock_window = None

if "lock_remaining" not in st.session_state:
    st.session_state.lock_remaining = 0

# ================= AUTO RESET THEO NGÀY ================= #

if st.session_state.engine_date != today:
    st.session_state.data = []
    st.session_state.lock_window = None
    st.session_state.lock_remaining = 0
    st.session_state.engine_date = today

    try:
        requests.post(
            WEBHOOK_URL,
            data=json.dumps({"action": "reset"}),
            headers={"Content-Type": "application/json"},
            timeout=5
        )
    except:
        pass

# ================= CORE LOGIC ================= #

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
    for i in range(w, 26):
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

def scan_best(data):
    best_score = 0
    best_w = None

    for w in range(6, 20):
        h = hits_26(data, w)
        if h < 6:
            continue
        s = streak(data, w)
        if s >= 3:
            score = h + s
            if score > best_score:
                best_score = score
                best_w = w

    return best_w

# ================= UI ================= #

st.title("🚀 Rolling Engine FINAL STABLE")

with st.form("engine_form"):
    input_str = st.text_input("Nhập chuỗi số (vd: 1,4,8,7,2):")
    submitted = st.form_submit_button("RUN")

if submitted and input_str:

    numbers = [int(x.strip()) for x in input_str.split(",") if x.strip().isdigit()]

    for n in numbers:

        group = get_group(n)
        predicted = None
        hit = None

        # ----- LOCK MODE -----
        if st.session_state.lock_window:

            w = st.session_state.lock_window

            if len(st.session_state.data) >= w:
                predicted = st.session_state.data[-w]["group"]
                hit = 1 if predicted == group else 0

            st.session_state.lock_remaining -= 1

            if st.session_state.lock_remaining <= 0:
                st.session_state.lock_window = None

        # ----- SCAN MODE -----
        if not st.session_state.lock_window:
            best_w = scan_best(st.session_state.data)
            if best_w:
                st.session_state.lock_window = best_w
                st.session_state.lock_remaining = LOCK_ROUNDS

        record = {
            "round": len(st.session_state.data) + 1,
            "number": n,
            "group": group,
            "predicted": predicted,
            "hit": hit,
            "window": st.session_state.lock_window
        }

        st.session_state.data.append(record)

        # ----- SEND TO GOOGLE SHEET -----
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
            requests.post(
                WEBHOOK_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=5
            )
        except:
            pass

    st.success("Đã xử lý và gửi Google Sheet")

# ================= DASHBOARD ================= #

st.divider()

st.metric("Tổng vòng", len(st.session_state.data))
st.metric("Active Window", st.session_state.lock_window)
st.metric("Lock Remaining", st.session_state.lock_remaining)

# ================= RESET ================= #

if st.button("RESET ENGINE + CLEAR SHEET"):

    st.session_state.data = []
    st.session_state.lock_window = None
    st.session_state.lock_remaining = 0

    try:
        requests.post(
            WEBHOOK_URL,
            data=json.dumps({"action": "reset"}),
            headers={"Content-Type": "application/json"},
            timeout=5
        )
    except:
        pass

    st.success("Đã reset engine và Google Sheet")
