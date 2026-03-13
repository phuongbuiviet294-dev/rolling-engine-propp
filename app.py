import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int)

st.title("V1400 Momentum Detector")

# group mapping
groups = numbers % 4

groups = groups.tolist()

n = len(groups)

repeat = 0

for i in range(n-1):
    if groups[i] == groups[i+1]:
        repeat += 1

repeat_prob = repeat/(n-1)

st.subheader("Repeat probability")

st.write(repeat_prob)

# conditional matrix

matrix = np.zeros((4,4))

for i in range(n-1):
    g = groups[i]
    g2 = groups[i+1]
    matrix[g][g2]+=1

matrix = matrix / matrix.sum(axis=1, keepdims=True)

st.subheader("Transition matrix")

st.dataframe(pd.DataFrame(matrix))

# streak test

streak2 = 0
streak3 = 0

for i in range(n-2):
    if groups[i]==groups[i+1]:
        streak2+=1
        if groups[i]==groups[i+2]:
            streak3+=1

if streak2>0:
    p3 = streak3/streak2
else:
    p3 = 0

st.subheader("P(streak3 | streak2)")

st.write(p3)
