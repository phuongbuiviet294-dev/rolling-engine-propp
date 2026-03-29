import pandas as pd
import numpy as np
import streamlit as st
from collections import Counter
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=10000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

ROLLING_SCAN = 182
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 5
VOTE_REQUIRED = 4

WIN = 2.5
LOSS = -1
GAP = 0

PROFIT_TARGET = 3
STOP_LOSS = -6

# ================= LOAD =================
@st.cache_data(ttl=10)
def load_data():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    df = pd.read_csv(url)
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_data()

def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

groups = [group(n) for n in numbers]

if len(groups) < ROLLING_SCAN:
    st.stop()

# ================= WINDOW EVAL =================
def evaluate(seq, w):
    profit = 0
    wins = 0
    trades = 0

    for i in range(w, len(seq)):
        pred = seq[i-w]
        if seq[i-1] != pred:
            trades += 1
            if seq[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

    winrate = wins / trades if trades else 0
    ev = winrate*WIN - (1-winrate)*abs(LOSS)

    return {
        "window": w,
        "profit": profit,
        "winrate": winrate,
        "ev": ev
    }

# ================= LOCK ONCE =================
if "locked_windows" not in st.session_state:

    train = groups[-ROLLING_SCAN:]

    rows = [evaluate(train, w) for w in range(WINDOW_MIN, WINDOW_MAX+1)]
    df = pd.DataFrame(rows)

    # chỉ lấy window dương
    good = df[df["profit"] > 0].sort_values("profit", ascending=False)

    # nếu >=4 thì dùng
    if len(good) >= 4:
        selected = good.head(TOP_WINDOWS)
    else:
        # fallback thêm ít xấu nhất
        df = df.sort_values(["profit","ev"], ascending=[False, False])
        selected = df.head(TOP_WINDOWS)

    st.session_state.locked_windows = selected["window"].tolist()

locked_windows = st.session_state.locked_windows

# ================= PROCESS =================
profit = 0
last_trade = -999
hits = []
curve = []
history = []

for i in range(ROLLING_SCAN, len(groups)):

    preds = [groups[i-w] for w in locked_windows if i-w >= 0]

    vote, count = Counter(preds).most_common(1)[0]
    signal = count >= VOTE_REQUIRED

    if profit >= PROFIT_TARGET or profit <= STOP_LOSS:
        trade = False
        state = "STOP"
    else:
        trade = signal and (i-last_trade >= GAP)
        state = "TRADE" if trade else "WAIT"

    hit = None

    if trade:
        last_trade = i
        if groups[i] == vote:
            profit += WIN
            hit = 1
            hits.append(1)
        else:
            profit += LOSS
            hit = 0
            hits.append(0)

    curve.append(profit)

    history.append({
        "round": i,
        "group": groups[i],
        "vote": vote,
        "signal": signal,
        "trade": trade,
        "hit": hit,
        "profit": profit,
        "state": state
    })

# ================= NEXT =================
next_round = len(groups)
preds = [groups[next_round-w] for w in locked_windows if next_round-w >= 0]

vote, count = Counter(preds).most_common(1)[0]

# ================= UI =================
st.title("🎯 Session Lock Engine (Stable)")

st.write("Locked Windows:", locked_windows)
st.write("Vote Required:", VOTE_REQUIRED)

st.metric("Profit", profit)
st.metric("Trades", len(hits))
st.metric("Winrate", round(np.mean(hits)*100,2) if hits else 0)

st.subheader("Next Group")
st.success(vote)

st.subheader("Profit Curve")
st.line_chart(curve)

st.subheader("History")
st.dataframe(pd.DataFrame(history).iloc[::-1])
