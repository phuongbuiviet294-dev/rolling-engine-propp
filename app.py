import streamlit as st
import pandas as pd
from collections import Counter
import numpy as np
import math

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

analysis=groups[-500:]

# ---------- pattern scanner ----------
def scan_patterns(g):

    best=None
    best_edge=0
    best_pred=None
    best_sample=0

    for L in [1,2,3,4]:

        if len(g)<L+50:
            continue

        key=tuple(g[-L:])

        nexts=[]

        for i in range(len(g)-L):

            if tuple(g[i:i+L])==key:

                nexts.append(g[i+L])

        sample=len(nexts)

        if sample<25:
            continue

        c=Counter(nexts)

        pred=max(c,key=c.get)

        prob=c[pred]/sample

        bias=prob-0.25

        if bias<0.03:
            continue

        edge=bias*math.log(sample)

        if edge>best_edge:

            best_edge=edge
            best=key
            best_pred=pred
            best_sample=sample

    return best,best_pred,best_edge,best_sample

# ---------- backtest ----------
profit=0
history=[]

for i in range(500,len(groups)-1):

    g=groups[i-500:i]

    pattern,pred,edge,sample=scan_patterns(g)

    hit=False

    if edge>0.18:

        if groups[i]==pred:

            profit+=2.5
            hit=True

        else:

            profit-=1

    else:

        pred=None

    history.append({
        "round":i,
        "actual":groups[i],
        "pred":pred,
        "hit":hit,
        "profit":profit,
        "edge":edge,
        "pattern":pattern
    })

hist=pd.DataFrame(history)

# ---------- metrics ----------
trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0

ev=wr*2.5-(1-wr)

drawdown=(hist.profit.cummax()-hist.profit).max()

pattern,pred,edge,sample=scan_patterns(analysis)

# ---------- UI ----------
st.title("🚀 V35 Bias Hunter Engine")

c1,c2,c3,c4=st.columns(4)

c1.metric("Rounds",len(groups))
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))
c4.metric("EV",round(ev,3))

c5,c6,c7=st.columns(3)

c5.metric("Profit",round(profit,2))
c6.metric("Drawdown",round(drawdown,2))
c7.metric("Edge Score",round(edge,3))

st.subheader("Best Pattern")

p1,p2,p3=st.columns(3)

p1.metric("Pattern",pattern)
p2.metric("Sample Size",sample)
p3.metric("Prediction",pred)

# ---------- next ----------
st.subheader("Next Group")

if edge>0.18:

    st.success(f"BET → {pred}")

else:

    st.info("SKIP")

# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(hist.profit)

# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(100))
