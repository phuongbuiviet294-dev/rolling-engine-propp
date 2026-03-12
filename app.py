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

analysis=groups[-200:]

# ---------- entropy ----------
def entropy(g):

    c=Counter(g)
    total=len(g)

    e=0
    for v in c.values():

        p=v/total
        e-=p*math.log2(p)

    return e

ent=entropy(analysis)

# ---------- models ----------
def markov1(g):

    cur=g[-1]
    trans=Counter()

    for i in range(len(g)-1):

        if g[i]==cur:

            trans[g[i+1]]+=1

    total=sum(trans.values())

    if total<8:return None,0

    best=max(trans,key=trans.get)

    return best,trans[best]/total


def markov2(g):

    if len(g)<3:return None,0

    key=(g[-2],g[-1])
    trans=Counter()

    for i in range(len(g)-2):

        if (g[i],g[i+1])==key:

            trans[g[i+2]]+=1

    total=sum(trans.values())

    if total<6:return None,0

    best=max(trans,key=trans.get)

    return best,trans[best]/total


def pattern(g):

    if len(g)<10:return None,0

    key=tuple(g[-3:])
    nexts=[]

    for i in range(len(g)-3):

        if tuple(g[i:i+3])==key:

            nexts.append(g[i+3])

    if len(nexts)<6:return None,0

    c=Counter(nexts)

    best=max(c,key=c.get)

    return best,c[best]/len(nexts)


# ---------- detect ----------
def detect(g):

    probs={1:0,2:0,3:0,4:0}

    p1,s1=markov1(g)
    p2,s2=markov2(g)
    p3,s3=pattern(g)

    if p1:probs[p1]+=s1*0.25
    if p2:probs[p2]+=s2*0.40
    if p3:probs[p3]+=s3*0.35

    ranked=sorted(probs.items(),key=lambda x:x[1],reverse=True)

    best,strength=ranked[0]
    second=ranked[1][1]

    gap=strength-second

    return best,strength,gap


# ---------- collect strengths ----------
strengths=[]

for i in range(200,len(groups)-1):

    g=groups[max(0,i-200):i]

    best,strength,gap=detect(g)

    strengths.append(strength)

# dynamic threshold
th=np.percentile(strengths,92)

# ---------- backtest ----------
profit=0
history=[]

for i in range(200,len(groups)-1):

    g=groups[max(0,i-200):i]

    pred,strength,gap=detect(g)

    hit=False

    if strength>th and gap>0.08:

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
        "strength":strength
    })

hist=pd.DataFrame(history)

# ---------- metrics ----------
trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0

ev=wr*2.5-(1-wr)

drawdown=(hist.profit.cummax()-hist.profit).max()

# ---------- UI ----------
st.title("⚡ V33 FINAL EDGE ENGINE")

c1,c2,c3,c4=st.columns(4)

c1.metric("Rounds",len(groups))
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))
c4.metric("EV",round(ev,3))

c5,c6,c7=st.columns(3)

c5.metric("Profit",round(profit,2))
c6.metric("Drawdown",round(drawdown,2))
c7.metric("Entropy",round(ent,3))

# ---------- next ----------
st.subheader("Next Group")

pred,strength,gap=detect(analysis)

if strength>th and gap>0.08:

    st.success(f"BET → {pred}")

else:

    st.info("SKIP")

# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(hist.profit)

# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(100))
