import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime

# ================= CONFIG ================= #

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwOhy_gVKMRTL3JLWHLxYOniaSM7KgDYtoijiH5dC5xoxqcwYYhfwt_xihDT37cV7QA/exec"
LOCK_ROUNDS = 18

# ================= INIT ================= #

today = datetime.now().strftime("%Y-%m-%d")

if "engine_date" not in st.session_state:
    st.session_state.engine_date = today

if "data" not in st.session_state:
    st.session_state.data = []

if "lock_window" not in st.session_state:
    st.session_state.lock_window = None

if "lock_remaining" not in st.session_state:
    st.session_state.lock_remaining = 0

# ================= DAILY RESET ================= #

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

# ================= CORE ================= #

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
    return sum(
        1 for i in range(w, 26)
        if recent[i]["group"] == recent[i-w]["group"]
    )

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
    changes = sum(
        1 for i in range(1, len(recent))
        if recent[i]["group"] != recent[i-1]["group"]
    )
    return changes / 25

def winrate_26(data):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    hits = [d["hit"] for d in recent if d["hit"] is not None]
    if not hits:
        return 0
    return sum(hits) / len(hits) * 100

def score_window(data, w):
    h = hits_26(data, w)
    s = streak(data, w)

    if h < 5:
        return 0

    score = (h * 1.2) + (s * 2) + (winrate_26(data)/10)

    if volatility_26(data) > 0.65:
        score *= 0.8

    return score

def scan_best(data):
    best_score = 0
    best_w = None

    for w in range(6,20):
        sc = score_window(data, w)
        if sc > best_score:
            best_score = sc
            best_w = w

    confidence = min(100, best_score * 4)

    return best_w, confidence

# ================= UI ================= #

st.title("🚀 Rolling Engine PRO++++")

with st.form("engine_form"):
    input_str = st.text_input("Nhập chuỗi số (vd: 1,4,8,7,2):")
    submitted = st.form_submit_button("RUN")

if submitted and input_str:

    numbers = [int(x.strip()) for x in input_str.split(",") if x.strip().isdigit()]

    for n in numbers:

        group = get_group(n)
        predicted = None
        hit = None

        # ===== LOCK MODE =====
        if st.session_state.lock_window:

            w = st.session_state.lock_window

            if len(st.session_state.data) >= w:
                predicted = st.session_state.data[-w]["group"]
                hit = 1 if predicted == group else 0

            st.session_state.lock_remaining -= 1

            if st.session_state.lock_remaining <= 0:
                st.session_state.lock_window = None

        # ===== SCAN MODE =====
        if not st.session_state.lock_window:
            best_w, conf = scan_best(st.session_state.data)
            if best_w:
                st.session_state.lock_window = best_w
                st.session_state.lock_remaining = LOCK_ROUNDS

        # ===== NEXT GROUP =====
        next_group = None
        if st.session_state.lock_window and len(st.session_state.data) >= st.session_state.lock_window:
            next_group = st.session_state.data[-st.session_state.lock_window]["group"]

        record = {
            "round": len(st.session_state.data) + 1,
            "number": n,
            "group": group,
            "predicted": predicted,
            "hit": hit,
            "window": st.session_state.lock_window,
            "next_group": next_group
        }

        st.session_state.data.append(record)

        payload = {
            "round": record["round"],
            "number": record["number"],
            "group": record["group"],
            "predicted": record["predicted"],
            "hit": record["hit"],
            "window": record["window"],
            "state": "LOCK" if st.session_state.lock_window else "SCAN",
            "next_group": next_group
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
st.metric("Winrate 26", round(winrate_26(st.session_state.data),2))

# NEXT PREDICT DISPLAY
if st.session_state.data and st.session_state.lock_window:
    last = st.session_state.data[-1]
    if last["next_group"]:
        st.markdown(
            f"""
            <div style='padding:15px;
                        background-color:#1f4e79;
                        color:white;
                        border-radius:10px;
                        text-align:center;
                        font-size:28px;
                        font-weight:bold'>
                🎯 NEXT PREDICTED GROUP: {last["next_group"]}
            </div>
            """,
            unsafe_allow_html=True
        )

# ================= HISTORY ================= #

if st.session_state.data:

    df = pd.DataFrame(st.session_state.data)

    def highlight_row(row):
        style = [""] * len(row)

        if row.name == df.index[-1]:
            style = ["background-color: #2e7d32; color:white"] * len(row)

        if row["hit"] == 1:
            style[df.columns.get_loc("hit")] = "background-color: green; color:white"

        return style

    st.subheader("History")
    st.dataframe(
        df.style.apply(highlight_row, axis=1),
        use_container_width=True
    )

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
