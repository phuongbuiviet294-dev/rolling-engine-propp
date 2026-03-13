import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE = 2000
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

st.title("🚀 V600 Hit-Streak Engine")


# =====================
# SIMPLE WINDOW MODEL
# =====================

predictions = []

for i in range(WINDOW, len(groups)):
    pred = groups[i-WINDOW]
    predictions.append(pred)

real = groups[WINDOW:]


# =====================
# HIT / MISS SERIES
# =====================

hits = []

for p,r in zip(predictions, real):
    if p == r:
        hits.append(1)
    else:
        hits.append(0)


# =====================
# STREAK ANALYSIS
# =====================

streaks=[]
current=0

for h in hits:

    if h==1:
        current+=1
    else:
        if current>0:
            streaks.append(current)
        current=0

if current>0:
    streaks.append(current)


st.subheader("Hit Streak Distribution")

dist=pd.Series(streaks).value_counts().sort_index()

st.dataframe(dist)


# =====================
# TRADING SIMULATION
# =====================

profit=0
equity=[]

in_trade=False

for h in hits:

    if not in_trade:

        if h==1:
            in_trade=True
            profit+=1

    else:

        if h==1:
            profit+=1

        else:
            profit-=1
            in_trade=False

    equity.append(profit)


st.subheader("Trading Result")

st.metric("Total Profit", profit)

st.line_chart(equity)
