import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE = 2000
WINDOW_RANGE = range(6,19)
MAX_STREAK = 10

WIN = 2.5
LOSS = 1


def get_group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


@st.cache_data(ttl=5)
def load():
    df = pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()


numbers = load()
groups = [get_group(n) for n in numbers]

st.title("🚀 V410 Walk-Forward Edge Test")


# -------------------
# TRAIN PHASE
# -------------------

train_groups = groups[:TRAIN_SIZE]

patterns = []

for window in WINDOW_RANGE:

    hits = []

    for i in range(window, len(train_groups)):
        hit = 1 if train_groups[i] == train_groups[i-window] else 0
        hits.append(hit)

    streak = 0

    for i in range(len(hits)-1):

        if hits[i] == 0:
            streak += 1
        else:
            streak = 0

        if streak>0 and streak<=MAX_STREAK:

            next_hit = hits[i+1]

            patterns.append({
                "window":window,
                "streak":streak,
                "hit":next_hit
            })


df = pd.DataFrame(patterns)

summary = []

for (window, streak), g in df.groupby(["window","streak"]):

    trades = len(g)
    winrate = g["hit"].mean()

    ev = winrate*WIN - (1-winrate)*LOSS

    summary.append({
        "window":window,
        "streak":streak,
        "trades":trades,
        "winrate":winrate,
        "EV":ev
    })

summary_df = pd.DataFrame(summary)

best = summary_df.sort_values("EV", ascending=False).iloc[0]

best_window = int(best.window)
best_streak = int(best.streak)

st.subheader("Best Pattern (TRAIN 2000)")
st.success(f"window={best_window} | streak={best_streak} | winrate={round(best.winrate*100,2)}%")


# -------------------
# FORWARD TEST
# -------------------

equity = 0
curve = []
streak = 0
trades = 0
wins = 0

for i in range(TRAIN_SIZE, len(groups)):

    if groups[i] != groups[i-best_window]:
        streak += 1
    else:
        streak = 0

    if streak == best_streak:

        trades += 1

        if groups[i] == groups[i-best_window]:
            equity += WIN
            wins += 1
        else:
            equity -= LOSS

        streak = 0

    curve.append(equity)


winrate = wins/trades if trades>0 else 0

st.metric("Forward Profit", round(equity,2))
st.metric("Trades", trades)
st.metric("Winrate", round(winrate*100,2))

st.line_chart(curve)
