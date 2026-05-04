import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=5000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 6
VOTE_REQUIRED = 4

GAP = 1

WIN = 2.5
LOSS = -1.0


# =========================
# LOAD DATA
# =========================
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={time.time()}"
    df = pd.read_csv(url)

    df.columns = [c.lower().strip() for c in df.columns]
    nums = pd.to_numeric(df["number"], errors="coerce").dropna().astype(int).tolist()

    return [x for x in nums if 1 <= x <= 12]


def group_of(n):
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


# =========================
# BUILD WINDOW
# =========================
def evaluate_window(seq, w):
    profit = 0
    trades = 0
    wins = 0

    for i in range(w, len(seq)):
        pred = seq[i - w]

        if seq[i - 1] != pred:
            trades += 1
            if seq[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

    wr = wins / trades if trades > 0 else 0
    score = profit + wr * 10 + np.log(trades + 1)

    return {"w": w, "score": score}


def pick_windows(groups):
    rows = [evaluate_window(groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows).sort_values("score", ascending=False)

    return df.head(TOP_WINDOWS)["w"].tolist()


# =========================
# MAIN ENGINE
# =========================
def run_engine(numbers):
    groups = [group_of(x) for x in numbers]

    if len(groups) < LOCK_ROUND_START:
        return None

    train = groups[:LOCK_ROUND_END]
    windows = pick_windows(train)

    hist = []

    last_live_trade = -999
    live_profit = 0
    paper_profit = 0

    for i in range(LOCK_ROUND_END, len(groups)):
        preds = [groups[i - w] for w in windows if i - w >= 0]

        if not preds:
            continue

        vote, conf = Counter(preds).most_common(1)[0]

        signal = conf >= VOTE_REQUIRED

        # ===== SIGNAL PROFIT =====
        if signal:
            if groups[i] == vote:
                signal_pnl = WIN
            else:
                signal_pnl = LOSS
        else:
            signal_pnl = 0

        paper_profit += signal_pnl

        # ===== PREVIOUS SIGNAL =====
        if len(hist) > 0:
            prev_signal_pnl = hist[-1]["signal_pnl"]
        else:
            prev_signal_pnl = 0

        distance = i - last_live_trade

        # ===== LIVE RULE =====
        live_trade = (
            signal
            and prev_signal_pnl > 0
            and distance >= GAP
        )

        if live_trade:
            last_live_trade = i

            if groups[i] == vote:
                live_pnl = WIN
            else:
                live_pnl = LOSS

            live_profit += live_pnl
        else:
            live_pnl = 0

        hist.append({
            "round": i + 1,
            "number": numbers[i],
            "group": groups[i],
            "vote": vote,
            "confidence": conf,
            "signal": signal,
            "signal_pnl": signal_pnl,
            "paper_profit": paper_profit,
            "prev_signal_pnl": prev_signal_pnl,
            "live_trade": live_trade,
            "live_pnl": live_pnl,
            "live_profit": live_profit,
            "profit_gap": paper_profit - live_profit
        })

    return pd.DataFrame(hist), windows


# =========================
# RUN
# =========================
numbers = load_numbers()
result = run_engine(numbers)

if result is None:
    st.error("Chưa đủ dữ liệu")
    st.stop()

hist, windows = result

# =========================
# NEXT ROUND
# =========================
groups = [group_of(x) for x in numbers]

i = len(groups)
preds = [groups[i - w] for w in windows if i - w >= 0]

vote, conf = Counter(preds).most_common(1)[0]
signal = conf >= VOTE_REQUIRED

if len(hist) > 0:
    prev_signal_pnl = hist.iloc[-1]["signal_pnl"]
else:
    prev_signal_pnl = 0

last_trade_rows = hist[hist["live_trade"] == True]
last_trade = last_trade_rows["round"].max() if len(last_trade_rows) else -999

distance = (i + 1) - last_trade

can_bet = signal and prev_signal_pnl > 0 and distance >= GAP

# =========================
# UI
# =========================
st.title("SAFE LIVE ENGINE FINAL")

c1, c2, c3 = st.columns(3)
c1.metric("Current", numbers[-1])
c2.metric("Group", groups[-1])
c3.metric("Next Group", vote)

st.write("Signal:", signal)
st.write("Prev Signal PNL:", prev_signal_pnl)
st.write("Distance:", distance)
st.write("Can Bet:", can_bet)
st.write("Windows:", windows)

if can_bet:
    st.success(f"READY BET GROUP {vote}")
else:
    st.warning("WAIT")

# =========================
# PROFIT COMPARE
# =========================
st.subheader("Profit Compare")

p1, p2, p3, p4 = st.columns(4)
p1.metric("Paper Profit", round(hist["paper_profit"].iloc[-1], 2))
p2.metric("Live Profit", round(hist["live_profit"].iloc[-1], 2))
p3.metric("Profit Gap", round(hist["profit_gap"].iloc[-1], 2))
p4.metric("Live Trades", int(hist["live_trade"].sum()))

# =========================
# STATS
# =========================
s1, s2, s3 = st.columns(3)
s1.metric("Signal Count", int(hist["signal"].sum()))
s2.metric("Signal Win", int((hist["signal_pnl"] > 0).sum()))
s3.metric("Signal Lose", int((hist["signal_pnl"] < 0).sum()))

# =========================
# CHART
# =========================
st.subheader("Profit Curve")
st.line_chart(hist[["paper_profit", "live_profit"]])

# =========================
# HISTORY
# =========================
st.subheader("History")
st.dataframe(hist.iloc[::-1].head(50))
