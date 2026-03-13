import streamlit as st
import pandas as pd
import numpy as np
from math import log

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int).tolist()

st.title("V810 RNG Reseed Timing Detector")

# block size
block_size = 200

blocks = []

for i in range(0, len(numbers), block_size):

    block = numbers[i:i+block_size]

    if len(block) < block_size:
        continue

    counts = pd.Series(block).value_counts()

    probs = counts / counts.sum()

    entropy = -(probs * np.log(probs)).sum()

    blocks.append({
        "start_round": i,
        "entropy": entropy,
        "max_prob": probs.max()
    })

df_blocks = pd.DataFrame(blocks)

st.subheader("Block Entropy")

st.dataframe(df_blocks)

st.line_chart(df_blocks["entropy"])

st.subheader("Max number probability")

st.line_chart(df_blocks["max_prob"])
