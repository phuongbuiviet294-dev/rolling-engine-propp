import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
from math import log2

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)
numbers = df["number"].dropna().astype(int).tolist()

st.title("🔬 V1200 Hidden Bias Detector")

# ---------------------------
# 1 Distribution test
# ---------------------------

counts = Counter(numbers)

dist = pd.DataFrame({
    "number": list(range(1,11)),
    "count": [counts.get(i,0) for i in range(1,11)]
})

dist["prob"] = dist["count"] / len(numbers)

st.subheader("Distribution")

st.dataframe(dist)

st.bar_chart(dist.set_index("number")["prob"])

# ---------------------------
# 2 Conditional probabilities
# ---------------------------

def conditional_prob(k):

    states = {}
    nexts = {}

    for i in range(k, len(numbers)-1):

        state = tuple(numbers[i-k:i])
        nxt = numbers[i]

        states.setdefault(state, 0)
        nexts.setdefault(state, [])

        states[state] += 1
        nexts[state].append(nxt)

    rows = []

    for s in states:

        if states[s] < 30:
            continue

        counts = Counter(nexts[s])
        probs = {n:counts[n]/states[s] for n in counts}

        rows.append({
            "state": s,
            "samples": states[s],
            "max_prob": max(probs.values())
        })

    return pd.DataFrame(rows)

st.subheader("Conditional Bias")

for k in [1,2,3]:

    res = conditional_prob(k)

    if res.empty:
        st.write(f"k={k}: no states")
        continue

    res = res.sort_values("max_prob", ascending=False)

    st.write(f"k={k} top states")

    st.dataframe(res.head(10))

# ---------------------------
# 3 Mutual Information
# ---------------------------

pairs = Counter(zip(numbers[:-1], numbers[1:]))

p_xy = {k:v/(len(numbers)-1) for k,v in pairs.items()}

p_x = Counter(numbers[:-1])
p_y = Counter(numbers[1:])

for k in p_x:
    p_x[k] /= len(numbers)

for k in p_y:
    p_y[k] /= len(numbers)

mi = 0

for (x,y),p in p_xy.items():

    mi += p * log2(p / (p_x[x]*p_y[y]))

st.subheader("Mutual Information")

st.write(mi)

# ---------------------------
# 4 KL divergence
# ---------------------------

uniform = 1/10

kl = sum(p*log2(p/uniform) for p in dist["prob"])

st.subheader("KL divergence from uniform")

st.write(kl)
