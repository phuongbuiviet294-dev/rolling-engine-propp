import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

# ---------------- CONFIG ----------------
DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
SCAN = 162
WINDOW_MIN = 6
WINDOW_MAX = 20
GAP = 4
WIN = 2.5
LOSS = -1

# ---------------- GROUP FUNCTION ----------------
def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=300)
def load_numbers():
    df = pd.read_csv(DATA_URL)
    df.columns = [c.lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    numbers = df["number"].dropna().astype(int).tolist()
    return numbers

numbers = load_numbers()
groups = [group(n) for n in numbers]

# ---------------- WINDOW SCAN ----------------
scan_groups = groups[:SCAN]
scan_results = []

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
    if trades > 0:  # tính tất cả window, không bỏ qua
        wr = wins / trades
        score = profit * wr * np.log(trades)
        scan_results.append({
            "window": w,
            "trades": trades,
            "wins": wins,
            "profit": profit,
            "winrate": wr,
            "score": score
        })

# Chọn top 3 window
scan_df = pd.DataFrame(scan_results).sort_values("score", ascending=False)
top_windows = scan_df.head(3)["window"].tolist()

st.subheader("Window Scan Results")
st.dataframe(scan_df.reset_index(drop=True))
st.markdown(f"**Top 3 windows selected:** {top_windows}")

# ---------------- TRADE ENGINE ----------------
profit = 0
last_trade = -999
history = []
hits = []

for i in range(SCAN, len(groups)):
    # vote dựa trên top windows
    preds = [groups[i-w] for w in top_windows]
    vote, confidence = Counter(preds).most_common(1)[0]
    
    signal = False
    trade = False
    bet_group = None
    hit = None
    state = "WAIT"
    
    if confidence >= 2 and groups[i-1] != vote:
        signal = True
        state = "SIGNAL"
        if (i - last_trade) >= GAP:
            trade = True
            state = "TRADE"
            bet_group = vote
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
        "state": state,
        "signal": signal,
        "trade": trade,
        "bet_group": bet_group,
        "hit": hit,
        "profit": profit
    })

hist = pd.DataFrame(history)

# ---------------- NEXT BET ----------------
i = len(groups) - 1
preds = [groups[i-w] for w in top_windows]
vote, confidence = Counter(preds).most_common(1)[0]
current_number = numbers[-1]
current_group = groups[-1]

last_trade_rows = hist[hist["trade"] == True]
distance = i - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999

signal = confidence >= 2 and current_group != vote
trade = signal and distance >= GAP

# ---------------- UI ----------------
st.title("🎯 NEXT BET")
col1, col2 = st.columns(2)
col1.metric("Current Number", current_number)
col2.metric("Current Group", current_group)
st.divider()

if trade:
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
    st.info("WAIT")

# ---------------- SESSION STATS ----------------
st.subheader("Session Statistics")
col1, col2, col3 = st.columns(3)
col1.metric("Profit", profit)
total_trades = len(hits)
col2.metric("Trades", total_trades)
wr = np.mean(hits) if len(hits) > 0 else 0
col3.metric("Winrate %", round(wr*100, 2))

# ---------------- PROFIT CURVE ----------------
st.subheader("Profit Curve")
if len(hist) > 0:
    st.line_chart(hist["profit"])

# ---------------- HISTORY ----------------
st.subheader("History")
st.dataframe(hist.iloc[::-1])
