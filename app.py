import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW_RANGE = range(6,19)
MAX_STREAK = 10

WIN = 2.5
LOSS = 1

# -------- group --------

def get_group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4

# -------- load --------

@st.cache_data(ttl=5)
def load():
    df = pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers = load()
groups = [get_group(n) for n in numbers]

st.title("🔎 V400 Pattern Scanner Engine")

results = []

# -------- scan windows --------

for window in WINDOW_RANGE:

    hits = []

    for i in range(window, len(groups)):
        hit = 1 if groups[i] == groups[i-window] else 0
        hits.append(hit)

    # compute streaks
    streak = 0

    for i in range(len(hits)-1):

        if hits[i] == 0:
            streak += 1
        else:
            streak = 0

        if streak > 0 and streak <= MAX_STREAK:

            next_hit = hits[i+1]

            results.append({
                "window":window,
                "streak":streak,
                "hit":next_hit
            })

# -------- dataframe --------

df = pd.DataFrame(results)

summary = []

for (window, streak), g in df.groupby(["window","streak"]):

    trades = len(g)
    winrate = g["hit"].mean()

    ev = winrate*WIN - (1-winrate)*LOSS

    summary.append({
        "window":window,
        "streak":streak,
        "trades":trades,
        "winrate":round(winrate*100,2),
        "EV":round(ev,3)
    })

summary_df = pd.DataFrame(summary)

summary_df = summary_df.sort_values("EV", ascending=False)

st.subheader("Pattern Edge Ranking")

st.dataframe(summary_df, use_container_width=True)

# -------- best pattern --------

best = summary_df.iloc[0]

st.subheader("Best Pattern Found")

st.success(
    f"""
window = {best.window}

streak = {best.streak}

winrate = {best.winrate}%

EV = {best.EV}
"""
)
