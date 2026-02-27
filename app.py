import streamlit as st
import pandas as pd
import math

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
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
    for w in range(6, 20):
        sc = score_window(data, w)
        if sc > 0:
            res.append((w, sc))
    res.sort(key=lambda x: x[1], reverse=True)
    return res

# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

engine = []
miss_streak = 0
pause_counter = 0

# ================= ENGINE LOOP ================= #

for i, n in enumerate(numbers):

    g = get_group(n)
    predicted = None
    hit = None
    best_window = None
    confidence_value = None
    state = "SCAN"

    # ===== PAUSE MODE =====
    if pause_counter > 0:
        pause_counter -= 1
        state = "PAUSE"

    # ===== SCAN & TRADE =====
    elif len(engine) >= 26:

        top = scan(engine)

        if top:
            total_score = sum(sc for w, sc in top[:3])
            confidence_value = round((top[0][1] / total_score) * 100, 2)

            if confidence_value >= 55:

                best_window = top[0][0]

                if len(engine) >= best_window:
                    predicted = engine[-best_window]["group"]
                    hit = 1 if predicted == g else 0
                    state = "TRADE"

                    if hit == 0:
                        miss_streak += 1
                    else:
                        miss_streak = 0

                    # ===== RESET CONDITION =====
                    if miss_streak >= 3:
                        pause_counter = 3
                        miss_streak = 0

    engine.append({
        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": best_window,
        "confidence_%": confidence_value,
        "state": state
    })

# ================= DASHBOARD ================= #

st.title("🚀 CONTINUOUS PRO ENGINE")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Rounds", len(engine))
col2.metric("Miss Streak", miss_streak)
col3.metric("Pause Counter", pause_counter)
col4.metric("Last State", engine[-1]["state"])

# ===== METRICS =====

hits = [x["hit"] for x in engine if x["hit"] is not None]

if len(hits) > 0:
    wr = sum(hits) / len(hits)
    ev = wr*25 - (1-wr)*10

    st.metric("Winrate", round(wr*100,2))
    st.metric("EV per Trade", round(ev,2))

# ===== NEXT GROUP =====

next_group = None
if len(engine) >= 1:
    latest_window = engine[-1]["window"]
    if latest_window and len(engine) >= latest_window:
        next_group = engine[-latest_window]["group"]

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

# ===== HISTORY =====

st.subheader("History")
df_engine = pd.DataFrame(engine)
st.dataframe(df_engine.iloc[::-1], use_container_width=True)

st.caption("CONTINUOUS PRO | No Lock | Auto Reset on 0-0-0 | Adaptive Window")
