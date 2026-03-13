import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int).tolist()

st.title("V1600 RNG Weakness Scanner")

n = len(numbers)

# ---------- 1 Markov test ----------

matrix = np.zeros((10,10))

for i in range(n-1):
    a = numbers[i]-1
    b = numbers[i+1]-1
    matrix[a][b]+=1

matrix = matrix / matrix.sum(axis=1, keepdims=True)

st.subheader("Markov transition matrix")

st.dataframe(pd.DataFrame(matrix))

# ---------- 2 Predictability ----------

correct = 0
total = 0

for i in range(5,n-1):

    hist = numbers[i-5:i]

    most_common = Counter(hist).most_common(1)[0][0]

    if numbers[i]==most_common:
        correct+=1

    total+=1

accuracy = correct/total

st.subheader("Simple predictor accuracy")

st.write(accuracy)

# ---------- 3 Cycle detection ----------

cycles = {}

for window in range(5,50):

    patterns = {}

    for i in range(n-window):

        seq = tuple(numbers[i:i+window])

        if seq in patterns:
            cycles[window]=True
            break
        else:
            patterns[seq]=1

st.subheader("Cycle detection")

st.write(cycles)
