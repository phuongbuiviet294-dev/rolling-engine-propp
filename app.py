import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN = 182
WINDOW_MIN = 6
WINDOW_MAX = 20

GAP = 4

TARGET = 10
STOP = -10

WIN = 2.5
LOSS = -1


# ---------------- GROUP ----------------

def group(n):
    if n <= 3:
        return 1
    elif n <= 6:
        return 2
    elif n <= 9:
        return 3
    else:
        return 4


# ---------------- LOAD DATA ----------------

@st.cache_data(ttl=5)
def load_data():
    df = pd.read_csv(DATA_URL)
    df.columns = [c.lower() for c in df.columns]
    numbers = df["number"].dropna().astype(int).tolist()
    return numbers


numbers = load_data()

if len(numbers) < SCAN:
    st.error("Not enough data yet")
    st.stop()

groups = [group(n) for n in numbers]


# ---------------- WINDOW SCAN ----------------

scan_groups = groups[:SCAN]

results = []

for window in range(WINDOW_MIN, WINDOW_MAX + 1):

    profit = 0
    trades = 0
    wins = 0

    for i in range(window, len(scan_groups)):

        pred = scan_groups[i-window]

        if scan_groups[i-1] != pred:

            trades += 1

            if scan_groups[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

    if trades > 10:

        winrate = wins / trades
        score = profit * winrate * np.log(trades)

        results.append({
            "window": window,
            "profit": profit,
            "trades": trades,
            "winrate": winrate,
            "score": score
        })


scan_df = pd.DataFrame(results)

if scan_df.empty:
    st.error("No valid window found")
    st.stop()

scan_df = scan_df.sort_values("score", ascending=False)

TOP = scan_df.head(3)

top_windows = TOP["window"].tolist()

st.subheader("Top Windows")

st.dataframe(TOP)


# ---------------- TRADE ENGINE ----------------

profit = 0
last_trade = -999

history = []
hits = []

for i in range(SCAN, len(groups)):

    preds = [groups[i-w] for w in top_windows]

    c = Counter(preds)

    vote, confidence = c.most_common(1)[0]

    signal = False
    hit = None

    if confidence >= 2 and groups[i-1] != vote and (i-last_trade) >= GAP:

        signal = True
        last_trade = i

        if groups[i] == vote:
            profit += WIN
            hit = 1
            hits.append(1)
        else:
            profit += LOSS
            hit = 0
            hits.append(0)

    history.append({
        "round": i,
        "number": numbers[i],
        "group": groups[i],
        "predictions": preds,
        "vote": vote,
        "confidence": confidence,
        "signal": signal,
        "hit": hit,
        "profit": profit
    })

    if profit >= TARGET or profit <= STOP:
        break


hist = pd.DataFrame(history)


# ---------------- SESSION RESULT ----------------

st.subheader("Session Result")

col1, col2, col3 = st.columns(3)

col1.metric("Profit", profit)

trades = len(hits)

col2.metric("Trades", trades)

winrate = np.mean(hits) if trades > 0 else 0

col3.metric("Winrate %", round(winrate * 100, 2))


# ---------------- EQUITY CURVE ----------------

st.subheader("Equity Curve")

if not hist.empty and "profit" in hist.columns:
    st.line_chart(hist["profit"])
else:
    st.info("No trades yet")


# ---------------- NEXT SIGNAL ----------------

preds = [groups[-w] for w in top_windows]

c = Counter(preds)

vote, confidence = c.most_common(1)[0]

st.subheader("Next Signal")

col1, col2 = st.columns(2)

col1.metric("Current Number", numbers[-1])
col2.metric("Current Group", groups[-1])

st.write("Predictions:", preds)
st.write("Confidence:", confidence)

if confidence >= 2 and groups[-1] != vote:
    st.success(f"🔥 BET GROUP {vote}")
else:
    st.warning("WAIT")


# ---------------- HISTORY ----------------

st.subheader("History")

if not hist.empty:
    st.dataframe(hist.iloc[::-1])
else:
    st.info("No history yet")
