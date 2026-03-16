import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
import time
from streamlit_autorefresh import st_autorefresh

# ---------------- AUTO REFRESH ----------------
st_autorefresh(interval=10000, key="refresh")  # refresh 10s

# ---------------- CONFIG ----------------
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

SCAN = 168
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 8       # số window lock
VOTE_REQUIRED = 5     # vote cần để trade
GAP = 1               # khoảng cách trade tối thiểu

WIN = 2.5
LOSS = -1

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    numbers = df["number"].dropna().astype(int).tolist()
    return numbers

numbers = load_numbers()

# ---------------- GROUP ----------------
def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

groups = [group(n) for n in numbers]

# ---------------- WINDOW SCAN ----------------
scan_groups = groups[-SCAN:]

def scan_windows(scan_groups):
    results = []
    for w in range(WINDOW_MIN, WINDOW_MAX+1):
        profit = 0
        trades = 0
        wins = 0
        for i in range(w, len(scan_groups)):
            pred = scan_groups[i-w]
            if scan_groups[i-1] != pred:
                trades += 1
                if scan_groups[i] == pred:
                    profit += WIN
                    wins += 1
                else:
                    profit += LOSS
        if trades > 0:
            wr = wins / trades
            score = profit * wr * np.log(trades)
            results.append({
                "window": w,
                "trades": trades,
                "wins": wins,
                "profit": profit,
                "winrate": wr,
                "score": score
            })
    return pd.DataFrame(results).sort_values("score", ascending=False)

# ---------------- LOCK WINDOWS ----------------
if "top_windows" not in st.session_state:
    scan_df = scan_windows(scan_groups)
    st.session_state.top_windows = scan_df.head(TOP_WINDOWS)["window"].tolist()

top_windows = st.session_state.top_windows

if st.button("🔄 Re-scan Windows"):
    scan_df = scan_windows(scan_groups)
    st.session_state.top_windows = scan_df.head(TOP_WINDOWS)["window"].tolist()
    st.rerun()

# ---------------- TRADE ENGINE ----------------
profit = 0
last_trade = -999
history = []
hits = []

start_index = max(SCAN, WINDOW_MAX)

for i in range(start_index, len(groups)):
    preds = [groups[i-w] for w in top_windows]  # luôn dùng windows lock
    vote, confidence = Counter(preds).most_common(1)[0]

    signal = confidence >= VOTE_REQUIRED and groups[i-1] != vote
    distance = i - last_trade
    trade = signal and distance >= GAP

    bet_group = vote if trade else None
    hit = None
    state = "WAIT"

    if signal:
        state = "SIGNAL"
    if trade:
        state = "TRADE"
        last_trade = i
        if groups[i] == vote:
            hit = 1
            profit += WIN
            hits.append(1)
        else:
            hit = 0
            profit += LOSS
            hits.append(0)

    history.append({
        "round": i,
        "number": numbers[i],
        "group": groups[i],
        "vote": vote,
        "confidence": confidence,
        "signal": signal,
        "trade": trade,
        "bet_group": bet_group,
        "hit": hit,
        "state": state,
        "profit": profit   # chỉ cộng khi trade thật
    })

hist = pd.DataFrame(history)

# ---------------- NEXT BET (prediction) ----------------
i = len(groups)
preds = [groups[i-w] for w in top_windows]
vote, confidence = Counter(preds).most_common(1)[0]
current_number = numbers[-1]
current_group = groups[-1]

last_trade_rows = hist[hist["trade"]==True]
distance = i - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999

signal = confidence >= VOTE_REQUIRED and current_group != vote
trade = False  # prediction row không cộng profit

next_row = {
    "round": i,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "signal": signal,
    "trade": trade,
    "bet_group": vote if signal else None,
    "hit": None,
    "state": "NEXT",
    "profit": profit   # giữ nguyên profit cuối cùng
}

hist = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Rolling Prediction Engine (GAP=1)")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number)
col2.metric("Current Group", current_group)
col3.metric("Next Group", vote)

st.divider()
st.write("Vote Strength:", confidence)
st.write("Distance From Last Trade:", distance)

# hiển thị Next Group prediction luôn (vàng)
st.markdown(f"""
<div style="background:#ffd700;
padding:20px;
border-radius:10px;
text-align:center;
font-size:28px;
font-weight:bold;">
NEXT GROUP → {vote} (Vote Strength: {confidence})
</div>
""", unsafe_allow_html=True)

# BET đỏ chỉ khi trade thật
if signal and distance>=GAP:
    st.markdown(f"""
    <div style="background:#ff4b4b;
    padding:25px;
    border-radius:10px;
    text-align:center;
    font-size:32px;
    color:white;
    font-weight:bold;">
    BET GROUP → {vote}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("WAIT (conditions not met)")

# ---------------- SESSION STATS ----------------
st.subheader("Session Statistics")
col1, col2, col3 = st.columns(3)
col1.metric("Profit", profit)
trades = len(hits)
col2.metric("Trades", trades)
wr = np.mean(hits) if trades > 0 else 0
col3.metric("Winrate %", round(wr*100,2))

# ---------------- PROFIT CURVE ----------------
st.subheader("Profit Curve")
st.line_chart(hist["profit"])

# ---------------- WINDOW SCAN ----------------
st.subheader("Window Scan")
st.dataframe(scan_df, use_container_width=True)

# ---------------- HISTORY ----------------
st.subheader("History")

def highlight_trade(row):
    if row["state"]=="NEXT":
        return ['background-color: #ffd700']*len(row)  # Next Group prediction
    elif row["trade"]:
        return ['background-color: #ff4b4b; color:white']*len(row)  # Trade thật
    return ['']*len(row)

st.dataframe(hist.iloc[::-1].style.apply(highlight_trade, axis=1), use_container_width=True)

# ---------------- DEBUG ----------------
st.write("Top Windows (locked):", top_windows)
st.write("Total Rows:", len(numbers))
