import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW = 50


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

st.title("🚀 V700 Regime Detection Engine")

entropy_series = []
imbalance_series = []


for i in range(WINDOW, len(groups)):

    window = groups[i-WINDOW:i]

    counts = [window.count(g) for g in range(1,5)]

    probs = [c/WINDOW for c in counts]

    entropy = -sum([p*np.log(p) for p in probs if p>0])

    entropy_series.append(entropy)

    imbalance = max(probs)

    imbalance_series.append(imbalance)


df_regime = pd.DataFrame({
    "entropy": entropy_series,
    "max_group_prob": imbalance_series
})


st.subheader("Entropy (randomness level)")

st.line_chart(df_regime["entropy"])


st.subheader("Group Imbalance")

st.line_chart(df_regime["max_group_prob"])


# detect strong regimes

threshold = 0.35

regimes = df_regime[df_regime["max_group_prob"] > threshold]

st.subheader("Detected Regimes")

st.dataframe(regimes.head(50))
