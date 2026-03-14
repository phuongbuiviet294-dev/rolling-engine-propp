import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=182
WINDOW_MIN=6
WINDOW_MAX=20

GAP=4

TARGET=10
STOP=-10

WIN=2.5
LOSS=-1


# -------- GROUP --------

def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# -------- LOAD DATA --------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()

groups=[group(n) for n in numbers]


# -------- WINDOW SCAN --------

scan_groups=groups[:SCAN]

results=[]

for w in range(WINDOW_MIN,WINDOW_MAX+1):

    profit=0
    trades=0
    wins=0

    for i in range(w,len(scan_groups)):

        pred=scan_groups[i-w]

        if scan_groups[i-1]!=pred:

            trades+=1

            if scan_groups[i]==pred:
                profit+=WIN
                wins+=1
            else:
                profit+=LOSS

    if trades>10:

        wr=wins/trades

        score=profit*wr*np.log(trades)

        results.append((w,score))


results.sort(key=lambda x:x[1],reverse=True)

top_windows=[x[0] for x in results[:3]]

# -------- NEXT SIGNAL --------

preds=[groups[-w] for w in top_windows]

c=Counter(preds)

vote,confidence=c.most_common(1)[0]


# -------- UI --------

st.title("⚡ Quick Trade Engine")

st.write("Top windows:",top_windows)

col1,col2=st.columns(2)

col1.metric("Confidence",confidence)

col2.metric("Last group",groups[-1])


if confidence>=2 and groups[-1]!=vote:

    st.success(f"BET GROUP {vote}")

else:

    st.warning("WAIT")


# -------- INFO --------

st.write("Predictions:",preds)

st.write("Current group:",groups[-1])
