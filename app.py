import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

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

st.title("V450 Transition Matrix Engine")

# =====================
# FIRST ORDER
# =====================

matrix = np.zeros((4,4))

for i in range(len(groups)-1):
    g1 = groups[i]-1
    g2 = groups[i+1]-1
    matrix[g1,g2] += 1

prob_matrix = matrix / matrix.sum(axis=1, keepdims=True)

st.subheader("First Order Transition Probability")

st.dataframe(
    pd.DataFrame(
        prob_matrix,
        columns=["next=1","next=2","next=3","next=4"],
        index=["curr=1","curr=2","curr=3","curr=4"]
    )
)

# =====================
# SECOND ORDER
# =====================

rows = []

for g1 in range(1,5):
    for g2 in range(1,5):

        counts = [0,0,0,0]

        for i in range(len(groups)-2):

            if groups[i]==g1 and groups[i+1]==g2:

                nxt = groups[i+2]-1
                counts[nxt]+=1

        total = sum(counts)

        if total > 20:

            probs = [c/total for c in counts]

            rows.append({
                "pattern":f"{g1}-{g2}",
                "next1":round(probs[0],3),
                "next2":round(probs[1],3),
                "next3":round(probs[2],3),
                "next4":round(probs[3],3),
                "samples":total
            })

df2 = pd.DataFrame(rows)

st.subheader("Second Order Markov")

st.dataframe(df2.sort_values("samples",ascending=False))
