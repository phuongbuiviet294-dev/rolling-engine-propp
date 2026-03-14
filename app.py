import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN = 182
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 5

GAP = 4

TARGET = 10
STOP = -5

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


scan_df = pd.DataFrame(results).sort_values("score", ascending=False)

TOP = scan_df.head(TOP_WINDOWS)

top_windows = TOP["window"].tolist()

st.subheader("Top Windows")
st.dataframe(TOP)


# ---------------- TRADE ENGINE ----------------

profit = 0
last_trade_index = -999

history = []

for i in range(SCAN, len(groups)):

    preds = []

    for w in top_windows:

        preds.append(groups[i-w])

    counter = Counter(preds)

    vote, confidence = counter.most_common(1)[0]

    signal = False
    hit = None

    if confidence >= 3 and groups[i-1] != vote and (i - last_trade_index) >= GAP:

        signal = True

        last_trade_index = i

        if groups[i] == vote:

            profit += WIN
            hit = 1

        else:

            profit += LOSS
            hit = 0


    history.append({
        "round": i,
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


# ---------------- DASHBOARD ----------------

st.subheader("Session Result")

col1,col2,col3 = st.columns(3)

col1.metric("Profit", profit)

trade_count = hist["hit"].count()

col2.metric("Trades", trade_count)

wr = hist["hit"].mean() if trade_count > 0 else 0

col3.metric("Winrate %", round(wr*100,2))


# ---------------- EQUITY ----------------

st.subheader("Equity Curve")

st.line_chart(hist["profit"])


# ---------------- NEXT SIGNAL ----------------

preds = []

for w in top_windows:
    preds.append(groups[-w])

counter = Counter(preds)

vote, confidence = counter.most_common(1)[0]

st.subheader("Next Signal")

if confidence >= 3 and groups[-1] != vote:

    st.success(f"BET GROUP {vote}")

else:

    st.info("WAIT")


# ---------------- HISTORY ----------------

st.subheader("History")

st.dataframe(hist.iloc[::-1])
