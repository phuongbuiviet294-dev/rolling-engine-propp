import streamlit as st
import pandas as pd
import numpy as np

st.title("Pattern Probability Scanner")

URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(URL)

numbers = df["number"].dropna().astype(int).values

def group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4

groups = np.array([group(x) for x in numbers])

WINDOW = 9

hits = []

for i in range(WINDOW,len(groups)):
    
    pred = groups[i-WINDOW]
    
    hit = 1 if groups[i]==pred else 0
    
    hits.append(hit)

hits = np.array(hits)

base_wr = hits.mean()

st.write("Base winrate:",base_wr)

patterns = {
    "1-1":[1,1],
    "1-0-1":[1,0,1],
    "0-1-1":[0,1,1],
    "1-1-1":[1,1,1],
    "0-0-1":[0,0,1],
}

results = []

for name,p in patterns.items():

    w = len(p)

    total = 0
    wins = 0

    for i in range(w,len(hits)):

        if list(hits[i-w:i]) == p:

            total += 1

            if hits[i]==1:
                wins += 1

    if total>0:

        wr = wins/total

        results.append((name,total,wr))

st.subheader("Pattern Results")

for r in results:

    st.write(r)
