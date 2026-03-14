import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN = 150
WINDOW_MIN = 6
WINDOW_MAX = 20

GAP = 4

TARGET = 10
STOP = -10

WIN = 2.5
LOSS = -1

st.set_page_config(layout="wide")

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

        # điều kiện signal
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
            "winrate": round(winrate,4),
            "score": score

        })


scan_df = pd.DataFrame(results).sort_values("score", ascending=False)

LOCK_WINDOW = int(scan_df.iloc[0]["window"])

st.subheader("Window Scan Result")
st.dataframe(scan_df)

st.success(f"LOCK WINDOW: {LOCK_WINDOW}")


# ---------------- TRADE ENGINE ----------------

profit = 0
last_trade_index = -999

history = []

for i in range(SCAN, len(groups)):

    pred = groups[i-LOCK_WINDOW]

    signal = False
    hit = None

    # signal condition
    if groups[i-1] != pred and (i - last_trade_index) >= GAP:

        signal = True
        last_trade_index = i

        if groups[i] == pred:

            profit += WIN
            hit = 1

        else:

            profit += LOSS
            hit = 0


    history.append({

        "round": i,
        "group": groups[i],
        "pred": pred,
        "signal": signal,
        "hit": hit,
        "profit": profit

    })


    if profit >= TARGET:
        break

    if profit <= STOP:
        break


hist = pd.DataFrame(history)


# ---------------- DASHBOARD ----------------

st.subheader("Session Result")

col1,col2,col3 = st.columns(3)

col1.metric("Profit", profit)

col2.metric("Trades", hist.hit.count())

wr = hist.hit.mean() if hist.hit.count() > 0 else 0

col3.metric("Winrate %", round(wr*100,2))


# ---------------- EQUITY ----------------

st.subheader("Equity Curve")

st.line_chart(hist.profit)


# ---------------- NEXT SIGNAL ----------------

pred = groups[-LOCK_WINDOW]

st.subheader("Next Signal")

if groups[-1] != pred:

    st.success(f"BET GROUP {pred}")

else:

    st.info("WAIT")


# ---------------- HISTORY ----------------

st.subheader("History")

st.dataframe(hist.iloc[::-1])
