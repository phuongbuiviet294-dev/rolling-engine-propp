import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW = 16

def get_group(n):
    if n <= 3:
        return 1
    elif n <= 6:
        return 2
    elif n <= 9:
        return 3
    else:
        return 4


df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int).tolist()

groups = [get_group(n) for n in numbers]


st.title("📊 V610 Streak Probability Engine")


# ====================
# MODEL PREDICTION
# ====================

predictions = []

for i in range(WINDOW, len(groups)):
    pred = groups[i-WINDOW]
    predictions.append(pred)

real = groups[WINDOW:]


# ====================
# HIT SERIES
# ====================

hits = []

for p, r in zip(predictions, real):
    if p == r:
        hits.append(1)
    else:
        hits.append(0)


# ====================
# STREAK PROBABILITY
# ====================

max_streak = 10

rows = []

for k in range(1, max_streak+1):

    next_hit = 0
    next_miss = 0

    for i in range(len(hits)-k):

        if hits[i:i+k] == [1]*k:

            nxt = hits[i+k]

            if nxt == 1:
                next_hit += 1
            else:
                next_miss += 1

    total = next_hit + next_miss

    if total == 0:
        continue

    prob = next_hit / total

    rows.append({
        "streak": k,
        "next_hit": next_hit,
        "next_miss": next_miss,
        "probability": round(prob,3)
    })


result = pd.DataFrame(rows)

st.subheader("P(next_hit | streak=k)")

st.dataframe(result)


# ====================
# PLOT
# ====================

st.line_chart(result.set_index("streak")["probability"])
