import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
import time
from streamlit_autorefresh import st_autorefresh

# ---------------- AUTO REFRESH ----------------
st_autorefresh(interval=1000, key="refresh")

# ---------------- CONFIG ----------------
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

SCAN = 168
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 8
VOTE_REQUIRED = 5
GAP = 1

WIN = 2.5
LOSS = -1

SCAN_LIST = [120,130,140,150,160,168,174,180]

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

# ---------------- GROUP ----------------
def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

groups = [group(n) for n in numbers]

# ---------------- WINDOW SCAN ----------------
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

# ---------------- AUTO WINDOW SELECT ----------------
def auto_select_windows(groups):
    window_counter = Counter()
    window_scores = {}

    for scan in SCAN_LIST:
        if len(groups) < scan:
            continue

        scan_groups = groups[:scan]
        scan_df = scan_windows(scan_groups)

        if scan_df is None or len(scan_df) == 0:
            continue

        top_ws = scan_df.head(TOP_WINDOWS)

        for _, row in top_ws.iterrows():
            w = int(row["window"])
            score = float(row["score"])

            window_counter[w] += 1

            if w not in window_scores:
                window_scores[w] = []
            window_scores[w].append(score)

    final_windows = []

    for w in window_counter:
        count = window_counter[w]
        avg_score = np.mean(window_scores[w])
        stability_score = count * avg_score
        final_windows.append((w, stability_score, count, avg_score))

    final_windows.sort(key=lambda x: x[1], reverse=True)

    return final_windows

# ---------------- LOCK WINDOWS ----------------
scan_groups = groups[:SCAN]
scan_df = scan_windows(scan_groups)

if "top_windows" not in st.session_state:
    result = auto_select_windows(groups)
    st.session_state.top_windows = [r[0] for r in result[:TOP_WINDOWS]]
    st.session_state.window_debug = result

top_windows = st.session_state.top_windows

if st.button("🔄 Re-optimize Windows"):
    result = auto_select_windows(groups)
    st.session_state.top_windows = [r[0] for r in result[:TOP_WINDOWS]]
    st.session_state.window_debug = result
    st.rerun()

# ---------------- TRADE ENGINE ----------------
profit = 0
last_trade = -999
history = []
hits = []

start_index = SCAN

for i in range(start_index, len(groups)):
    preds = [groups[i-w] for w in top_windows]
    vote, confidence = Counter(preds).most_common(1)[0]

    signal = confidence >= VOTE_REQUIRED
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
        "profit": profit
    })

hist = pd.DataFrame(history)

# ---------------- NEXT BET ----------------
i = len(groups)
preds = [groups[i-w] for w in top_windows]
vote, confidence = Counter(preds).most_common(1)[0]

current_number = numbers[-1]
current_group = groups[-1]

last_trade_rows = hist[hist["trade"]==True]
distance = i - last_trade_rows["round"].max() if len(last_trade_rows)>0 else 999

signal = confidence >= VOTE_REQUIRED

next_row = {
    "round": i,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "signal": signal,
    "trade": False,
    "bet_group": vote if signal else None,
    "hit": None,
    "state": "NEXT",
    "profit": profit
}

hist = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Rolling Engine - Auto Window Optimization")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number)
col2.metric("Current Group", current_group)
col3.metric("Next Group", vote)

st.write("Vote Strength:", confidence)
st.write("Distance:", distance)

# Next group
st.markdown(f"""
<div style="background:#ffd700;padding:20px;border-radius:10px;text-align:center;font-size:28px;font-weight:bold;">
NEXT GROUP → {vote}
</div>
""", unsafe_allow_html=True)

# Trade
if signal and distance >= GAP:
    st.markdown(f"""
    <div style="background:#ff4b4b;padding:25px;border-radius:10px;text-align:center;font-size:32px;color:white;font-weight:bold;">
    BET GROUP → {vote}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("WAIT")

# Stats
st.subheader("Stats")
col1, col2, col3 = st.columns(3)
col1.metric("Profit", profit)
col2.metric("Trades", len(hits))
col3.metric("Winrate", round(np.mean(hits)*100,2) if hits else 0)

# Chart
st.line_chart(hist["profit"])

# Scan table
st.subheader("Window Scan (168 đầu)")
st.dataframe(scan_df)

# Debug auto window
st.subheader("Auto Window Debug")
if "window_debug" in st.session_state:
    debug_df = pd.DataFrame(
        st.session_state.window_debug,
        columns=["window","stability_score","count","avg_score"]
    )
    st.dataframe(debug_df)

st.write("Final Windows:", top_windows)

# History
def highlight(row):
    if row["state"]=="NEXT":
        return ['background-color: #ffd700']*len(row)
    elif row["trade"]:
        return ['background-color: #ff4b4b; color:white']*len(row)
    return ['']*len(row)

st.subheader("History")
st.dataframe(hist.iloc[::-1].style.apply(highlight, axis=1))
