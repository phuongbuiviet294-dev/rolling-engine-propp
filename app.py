import streamlit as st
import pandas as pd
import math

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
LOCK_ROUNDS = 12   # 🔥 GIẢM TỪ 18 → 12
AUTO_REFRESH = 5

st.set_page_config(layout="wide")

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

def score_window(data, w):
    h = hits_26(data, w)
    if h < 5:
        return 0
    s = streak(data, w)
    return (h * 1.5) + (s * 3)

def scan(data):
    res = []
    for w in range(8, 20):   # scan 8–19
        sc = score_window(data, w)
        if sc > 0:
            res.append((w, sc))
    res.sort(key=lambda x: x[1], reverse=True)
    return res[:3]

# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

engine = []
lock_window = None
lock_remaining = 0
miss_streak = 0
confidence_value = None

# ================= ENGINE LOOP ================= #

for i, n in enumerate(numbers):

    g = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"

    # ===== LOCK MODE =====
    if lock_window is not None:

        state = "LOCK"

        if len(engine) >= lock_window:
            predicted = engine[-lock_window]["group"]
            hit = 1 if predicted == g else 0

            if hit == 0:
                miss_streak += 1
            else:
                miss_streak = 0

        lock_remaining -= 1

        if miss_streak >= 3:
            lock_window = None

        if lock_remaining <= 0:
            lock_window = None

    # ===== SCAN MODE =====
    if lock_window is None and len(engine) >= 26:

        top = scan(engine)

        if top:
            total_score = sum(sc for w, sc in top)
            confidence_value = round((top[0][1] / total_score) * 100, 2)

            p = confidence_value / 100
            ev = (p * 1) - (1 - p)

            if ev > 0 and confidence_value >= 50:

                votes = {}

                for w, sc in top:
                    if len(engine) >= w:
                        gr = engine[-w]["group"]
                        votes[gr] = votes.get(gr, 0) + sc

                best_group = max(votes, key=votes.get)

                for w, sc in top:
                    if len(engine) >= w and engine[-w]["group"] == best_group:
                        lock_window = w
                        break

                lock_remaining = LOCK_ROUNDS
                miss_streak = 0
                state = "LOCK_START"

    engine.append({
        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": lock_window,
        "confidence_%": confidence_value,
        "state": state
    })

# ================= DASHBOARD ================= #

st.title("🚀 PRO++++ CLEAN ENGINE (LOCK 12)")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Rounds", len(engine))
col2.metric("Active Window", lock_window)
col3.metric("Lock Remaining", lock_remaining)
col4.metric("Miss Streak", miss_streak)

if len(engine) >= 26:
    top = scan(engine)
    if top:
        total_score = sum(sc for w, sc in top)
        confidence = round((top[0][1] / total_score) * 100, 2)
        p = confidence / 100
        ev = round((p * 1) - (1 - p), 3)
        kelly = round(max(0, p - (1 - p)) * 100, 2)

        st.metric("Confidence %", confidence)
        st.metric("Expected Value", ev)
        st.metric("Kelly % Capital", kelly)

# NEXT GROUP
next_group = None
if lock_window is not None and len(engine) >= lock_window:
    next_group = engine[-lock_window]["group"]

if next_group:
    st.markdown(f"""
    <div style='padding:15px;
                background:#1f4e79;
                color:white;
                border-radius:10px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
        🎯 NEXT GROUP: {next_group}
    </div>
    """, unsafe_allow_html=True)

# HISTORY
st.subheader("History")
df_engine = pd.DataFrame(engine)
st.dataframe(df_engine.iloc[::-1], use_container_width=True)

st.caption("PRO++++ CLEAN MODE | LOCK 12 | SCAN 8–19 | Faster Adaptive")
