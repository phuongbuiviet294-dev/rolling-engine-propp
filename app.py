import streamlit as st
import requests
import json
import pandas as pd
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

def break_penalty(data):
    if len(data) < 4:
        return 0
    last4 = [d["hit"] for d in data[-4:]]
    if last4 == [1,0,1,0] or last4 == [0,1,0,1]:
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

def score_window(data, w):
    h = hits_26(data, w)
    s = streak(data, w)

    if h < 5:
        return 0

    base = (h * 1.2) + (s * 2) + (winrate_26(data)/10)
    base -= break_penalty(data)

    vol = volatility_26(data)
    if vol > 0.65:
        base *= 0.8

    return base

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

st.title("🚀 Rolling Engine PRO+++ COMPLETE")

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

                old_w = st.session_state.lock_window
                st.session_state.lock_window = None

                # RELock ưu tiên window cũ
                if score_window(st.session_state.data, old_w) > 6:
                    st.session_state.lock_window = old_w
                    st.session_state.lock_remaining = LOCK_ROUNDS

                # Nếu không relock được → scan mới
                if not st.session_state.lock_window:
                    best_w, conf = scan_best(st.session_state.data)
                    if best_w:
                        st.session_state.lock_window = best_w
                        st.session_state.lock_remaining = LOCK_ROUNDS

        # ===== SCAN MODE =====
        if not st.session_state.lock_window:
            best_w, conf = scan_best(st.session_state.data)
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

        # ===== SEND TO GOOGLE SHEET =====
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
st.metric("Winrate 26", round(winrate_26(st.session_state.data),2))

# ================= SCAN TABLE ================= #

st.subheader("📊 Window Scan 6–19")

rows = []
for w in range(6,20):
    rows.append({
        "Window": w,
        "Hits_26": hits_26(st.session_state.data, w),
        "Streak": streak(st.session_state.data, w),
        "Score": round(score_window(st.session_state.data, w),2)
    })

scan_df = pd.DataFrame(rows).sort_values("Score", ascending=False)

st.dataframe(
    scan_df.style.apply(
        lambda row: [
            "background-color: green" if row["Window"] == st.session_state.lock_window else ""
            for _ in row
        ],
        axis=1
    ),
    use_container_width=True
)

# ================= PERFORMANCE ================= #

st.subheader("📈 Performance")

if st.session_state.data:

    df = pd.DataFrame(st.session_state.data)
    df["Hit_Fill"] = df["hit"].fillna(0)
    df["Cumulative_Hits"] = df["Hit_Fill"].cumsum()
    df["Rolling_Winrate"] = df["Hit_Fill"].rolling(26).mean().fillna(0)*100

    st.line_chart(df.set_index("round")[["Cumulative_Hits"]])
    st.line_chart(df.set_index("round")[["Rolling_Winrate"]])

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
