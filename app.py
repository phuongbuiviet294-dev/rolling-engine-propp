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

analysis=groups[-600:]

# ---------- transition bias ----------
def transition_bias(g):

    trans={}

    for i in range(len(g)-1):

        a=g[i]
        b=g[i+1]

        if a not in trans:
            trans[a]=Counter()

        trans[a][b]+=1

    best=None
    best_pred=None
    best_edge=0
    best_z=0
    best_sample=0

    for cur in trans:

        total=sum(trans[cur].values())

        if total<50:
            continue

        for nxt in [1,2,3,4]:

            obs=trans[cur].get(nxt,0)

            p=obs/total

            bias=p-0.25

            se=math.sqrt(0.25*0.75/total)

            z=bias/se

            edge=abs(bias)*math.log(total)

            if abs(z)>2 and edge>best_edge:

                best_edge=edge
                best=(cur,nxt)
                best_pred=nxt
                best_z=z
                best_sample=total

    return best,best_pred,best_edge,best_z,best_sample

# ---------- backtest ----------
profit=0
history=[]

for i in range(600,len(groups)-1):

    g=groups[i-600:i]

    pattern,pred,edge,z,sample=transition_bias(g)

    hit=False

    if edge>0.08:

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
        "z":z
    })

hist=pd.DataFrame(history)

# ---------- metrics ----------
trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0

ev=wr*2.5-(1-wr)

drawdown=(hist.profit.cummax()-hist.profit).max()

pattern,pred,edge,z,sample=transition_bias(analysis)

# ---------- UI ----------
st.title("🔬 V36 Bias Microscope Engine")

c1,c2,c3,c4=st.columns(4)

c1.metric("Rounds",len(groups))
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))
c4.metric("EV",round(ev,3))

c5,c6,c7=st.columns(3)

c5.metric("Profit",round(profit,2))
c6.metric("Drawdown",round(drawdown,2))
c7.metric("Edge Score",round(edge,3))

st.subheader("Detected Bias")

p1,p2,p3,p4=st.columns(4)

p1.metric("Transition",pattern)
p2.metric("Sample Size",sample)
p3.metric("Z-score",round(z,2))
p4.metric("Prediction",pred)

# ---------- next ----------
st.subheader("Next Group")

if edge>0.08:

    st.success(f"BET → {pred}")

else:

    st.info("SKIP")

# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(hist.profit)

# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(100))
