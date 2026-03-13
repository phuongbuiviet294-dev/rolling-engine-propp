import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)
numbers = df["number"].dropna().astype(int).tolist()

st.title("V900 State Pattern Scan")

lookback = 5

states = {}
next_vals = {}

for i in range(lookback, len(numbers)-1):

    state = tuple(numbers[i-lookback:i])
    nxt = numbers[i+1]

    if state not in states:
        states[state] = 0
        next_vals[state] = []

    states[state] += 1
    next_vals[state].append(nxt)

results = []

for state in states:

    if states[state] < 20:
        continue

    counts = pd.Series(next_vals[state]).value_counts(normalize=True)

    max_prob = counts.max()

    results.append({
        "state": state,
        "samples": states[state],
        "max_next_prob": max_prob
    })

df_res = pd.DataFrame(results)

df_res = df_res.sort_values("max_next_prob", ascending=False)

st.dataframe(df_res.head(20))

st.bar_chart(df_res.head(20).set_index("state")["max_next_prob"])
