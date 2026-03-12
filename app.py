import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# ---------- group ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ---------- load ----------
@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()
groups=[group(n) for n in numbers]

# ---------- EDGE DETECTION ----------

def streak_edge(g):

    if len(g)<3:return None

    if g[-1]==g[-2]==g[-3]:

        return [x for x in [1,2,3,4] if x!=g[-1]]

    return None


def imbalance_edge(g):

    if len(g)<40:return None

    window=g[-40:]

    count=Counter(window)

    for i in range(1,5):
        count.setdefault(i,0)

    expected=10

    diff={i:expected-count[i] for i in count}

    best=max(diff,key=diff.get)

    if diff[best]>=4:

        return [best]

    return None


def cluster_edge(g):

    if len(g)<6:return None

    seq=g[-6:]

    if seq[0]==seq[2]==seq[4] and seq[1]==seq[3]==seq[5]:

        return [seq[-1],seq[-2]]

    return None


def detect_edge(g):

    for fn in [streak_edge,imbalance_edge,cluster_edge]:

        r=fn(g)

        if r:
            return r

    return None

# ---------- backtest ----------

profit=0
history=[]

for i in range(50,len(groups)-1):

    g=groups[:i]

    signal=detect_edge(g)

    pred=None
    hit=False

    if signal:

        pred=np.random.choice(signal)

        if groups[i]==pred:

            profit+=3

            hit=True

        else:

            profit-=1

    history.append({
        "round":i,
        "actual":groups[i],
        "pred":pred,
        "hit":hit,
        "profit":profit
    })

hist_df=pd.DataFrame(history)

# ---------- metrics ----------

trades=len(hist_df[hist_df.pred.notna()])

wins=len(hist_df[hist_df.hit==True])

wr=wins/trades if trades else 0

# ---------- UI ----------

st.title("⚡ V15 PRO Edge Engine")

col1,col2,col3=st.columns(3)

col1.metric("Profit",profit)
col2.metric("Trades",trades)
col3.metric("Winrate",round(wr*100,2))

# ---------- next group ----------

signal=detect_edge(groups)

st.subheader("Next Group")

if signal:

    st.success(f"BET → {signal}")

else:

    st.info("SKIP")

# ---------- equity ----------

st.subheader("Equity Curve")

st.line_chart(hist_df.profit)

# ---------- history ----------

st.subheader("History")

st.dataframe(hist_df.tail(50))
