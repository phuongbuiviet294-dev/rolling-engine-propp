import streamlit as st
import pandas as pd
import numpy as np
import random

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int).tolist()

st.title("V820 Permutation Test")


# ===== Strategy logic =====
def run_strategy(data):

    profit = 0

    for i in range(30, len(data)-1):

        # ví dụ signal giống logic cũ
        if data[i-1] == data[i-5]:

            pred = data[i-9]

            if data[i+1] == pred:
                profit += 1
            else:
                profit -= 1

    return profit


# real profit
real_profit = run_strategy(numbers)

st.write("Real dataset profit:", real_profit)


# ===== permutation test =====
N = 200

profits = []

for _ in range(N):

    shuffled = numbers.copy()

    random.shuffle(shuffled)

    p = run_strategy(shuffled)

    profits.append(p)


st.subheader("Shuffle profits")

st.line_chart(profits)

avg_profit = np.mean(profits)

st.write("Average shuffle profit:", avg_profit)

better = sum(1 for p in profits if p >= real_profit)

p_value = better / N

st.write("p-value:", p_value)
