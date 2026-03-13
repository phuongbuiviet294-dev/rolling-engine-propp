import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
from math import log2

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)
numbers = df["number"].dropna().astype(int).tolist()

st.title("🔎 V1300 Regime Detector")

block = 200

entropy_list = []
kl_list = []
maxprob_list = []
start_round = []

for i in range(0, len(numbers)-block, block):

    segment = numbers[i:i+block]

    counts = Counter(segment)

    probs = [counts.get(n,0)/block for n in range(1,11)]

    # entropy
    entropy = -sum(p*log2(p) for p in probs if p>0)

    # KL divergence
    uniform = 1/10
    kl = sum(p*log2(p/uniform) for p in probs if p>0)

    entropy_list.append(entropy)
    kl_list.append(kl)
    maxprob_list.append(max(probs))
    start_round.append(i)

res = pd.DataFrame({
    "start_round":start_round,
    "entropy":entropy_list,
    "kl":kl_list,
    "max_prob":maxprob_list
})

st.subheader("Block statistics")

st.dataframe(res)

st.subheader("Entropy over time")
st.line_chart(res.set_index("start_round")["entropy"])

st.subheader("KL divergence over time")
st.line_chart(res.set_index("start_round")["kl"])

st.subheader("Max number probability")
st.line_chart(res.set_index("start_round")["max_prob"])
