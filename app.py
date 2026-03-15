import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN = 168
WINDOW_MIN = 6
WINDOW_MAX = 20
GAP = 4

WIN = 2.5
LOSS = -1


# ---------- GROUP ----------
def group(n):
    if n <= 3:
        return 1
    elif n <= 6:
        return 2
    elif n <= 9:
        return 3
    else:
        return 4


# ---------- LOAD DATA ----------
@st.cache_data(ttl=5)
def load():

    df = pd.read_csv(DATA_URL)

    df.columns = [c.lower() for c in df.columns]

    df["number"] = pd.to_numeric(df["number"], errors="coerce")

    numbers = df["number"].dropna().astype(int).tolist()

    return numbers


numbers = load()

groups = [group(n) for n in numbers]


# ---------- WINDOW SCAN ----------
scan_groups = groups[:SCAN]

results = []

for w in range(WINDOW_MIN, WINDOW_MAX + 1):

    profit = 0
    trades = 0
    wins = 0

    for i in range(w, len(scan_groups)):

        pred = scan_groups[i - w]

        if scan_groups[i - 1] != pred:

            trades += 1

            if scan_groups[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

    if trades > 10:

        wr = wins / trades

        score = profit * wr * np.log(trades)

        results.append({
            "window": w,
            "score": score
        })


scan_df = pd.DataFrame(results).sort_values("score", ascending=False)

top_windows = scan_df.head(3)["window"].tolist()


# ---------- TRADE ENGINE ----------
profit = 0

last_trade = -999

history = []

hits = []

for i in range(SCAN, len(groups)):

    preds = [groups[i - w] for w in top_windows]

    vote, confidence = Counter(preds).most_common(1)[0]

    signal = False
    trade = False
    bet_group = None
    hit = None
    state = "WAIT"

    if confidence >= 2 and groups[i - 1] != vote:

        signal = True
        state = "SIGNAL"

        if (i - last_trade) >= GAP:

            trade = True
            bet_group = vote
            last_trade
