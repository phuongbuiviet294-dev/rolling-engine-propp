import streamlit as st
import pandas as pd
import math

# ================= CONFIG ================= #

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOCK_ROUNDS = 18
AUTO_REFRESH = 5

# ================= RISK MODE ================= #

risk_mode = st.sidebar.selectbox(
    "Risk Mode",
    ["Conservative", "Balanced", "Aggressive"]
)

if risk_mode == "Conservative":
    MIN_HITS = 6
elif risk_mode == "Balanced":
    MIN_HITS = 5
else:
    MIN_HITS = 4

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
        return 50
    recent = data[-26:]
    changes = sum(
        1 for i in range(1,26)
        if recent[i]["group"] != recent[i-1]["group"]
    )
    return changes/25

def momentum_bonus(data, w):
    if len(data) < w + 5:
        return 0
    count = 0
    for i in range(len(data)-5, len(data)):
        if data[i]["group"] == data[i-w]["group"]:
            count += 1
    return 5 if count >= 3 else 0

def score_window(data, w):
    h = hits_26(data, w)
    s = streak(data, w)

    if h < MIN_HITS:
        return 0

    score = (h * 1.5) + (s * 3)
    score += momentum_bonus(data, w)

    vol = volatility_26(data)

    if vol > 0.65:
        score *= 0.8
    elif vol < 0.4:
        score *= 1.1

    return score

def scan_windows(data):
    results = []
    for w in range(6,20):
        sc = score_window(data, w)
        if sc > 0:
            results.append((w, sc))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:3]

# ================= LOAD DATA ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load_data():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df_raw = load_data()

if df_raw.empty:
    st.warning("Sheet chưa có dữ liệu.")
    st.stop()

numbers = df_raw["number"].dropna().astype(int).tolist()

# ================= ENGINE ================= #

engine_data = []
lock_window = None
lock_remaining = 0
miss_streak = 0

for i, n in enumerate(numbers):

    group = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"

    if lock_window:

        state = "LOCK"

        if len(engine_data) >= lock_window:
            predicted = engine_data[-lock_window]["group"]
            hit = 1 if predicted == group else 0

            if hit == 0:
                miss_streak += 1
            else:
                miss_streak = 0

        lock_remaining -= 1

        if miss_streak >= 3:
            lock_window = None
            miss_streak = 0

        if lock_remaining <= 0:
            lock_window = None

    if not lock_window and len(engine_data) >= 20:

        top_windows = scan_windows(engine_data)

        if top_windows:

            votes = {}
            total_score = 0

            for w, sc in top_windows:
                total_score += sc
                if len(engine_data) >= w:
                    g = engine_data[-w]["group"]
                    votes[g] = votes.get(g,0) + sc

            best_group = max(votes, key=votes.get)

            for w, sc in top_windows:
                if len(engine_data) >= w and engine_data[-w]["group"] == best_group:
                    lock_window = w
                    break

            lock_remaining = LOCK_ROUNDS
            state = "LOCK_START"

    engine_data.append({
        "round": i+1,
        "number": n,
        "group": group,
        "predicted": predicted,
        "hit": hit,
        "window": lock_window,
        "state": state
    })

# ================= DASHBOARD ================= #

st.title("🚀 PRO+++++ AI Trading Engine")

st.metric("Total Rounds", len(engine_data))
st.metric("Active Window", lock_window)
st.metric("Lock Remaining", lock_remaining)
st.metric("Miss Streak", miss_streak)

# CONFIDENCE + EV
if len(engine_data) >= 26:
    top_windows = scan_windows(engine_data)
    if top_windows:
        total = sum(sc for w, sc in top_windows)
        confidence = round((top_windows[0][1] / total) * 100, 2)
        ev = round((confidence/100)*1 - (1-confidence/100), 3)
        st.metric("Confidence %", confidence)
        st.metric("Expected Value", ev)

# NEXT GROUP
next_group = None
if lock_window and len(engine_data) >= lock_window:
    next_group = engine_data[-lock_window]["group"]

if next_group:
    st.markdown(
        f"""
        <div style='padding:15px;
                    background:#1f4e79;
                    color:white;
                    border-radius:10px;
                    text-align:center;
                    font-size:28px;
                    font-weight:bold'>
            🎯 NEXT GROUP: {next_group}
        </div>
        """,
        unsafe_allow_html=True
    )

# HISTORY
df_engine = pd.DataFrame(engine_data)
df_display = df_engine.iloc[::-1].reset_index(drop=True)

st.subheader("History (Newest First)")
st.dataframe(df_display, use_container_width=True)

st.caption("PRO+++++ AI Mode | Bayesian Confidence | Multi-window Voting | Stop Protection")
