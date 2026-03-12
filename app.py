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

# ---------- entropy ----------
def entropy(g):

    c=Counter(g)
    total=len(g)

    e=0

    for v in c.values():

        p=v/total
        e-=p*math.log2(p)

    return e

# ---------- chi square ----------
def chi_square(g):

    c=Counter(g)

    total=len(g)

    expected=total/4

    chi=0

    for i in [1,2,3,4]:

        obs=c.get(i,0)

        chi+=(obs-expected)**2/expected

    return chi

# ---------- RNG detector ----------
def rng_bias(g):

    e=entropy(g)
    chi=chi_square(g)

    if e<1.97 and chi>6:

        return True

    return False

# ---------- pattern detector ----------
def pattern_bias(g):

    best=None
    best_prob=0

    for L in [1,2,3]:

        key=tuple(g[-L:])

        nexts=[]

        for i in range(len(g)-L):

            if tuple(g[i:i+L])==key:

                nexts.append(g[i+L])

        if len(nexts)<30:
            continue

        c=Counter(nexts)

        pred=max(c,key=c.get)

        prob=c[pred]/len(nexts)

        if prob>best_prob and prob>0.28:

            best_prob=prob
            best=pred

    return best

# ---------- transition detector ----------
def transition_bias(g):

    cur=g[-1]

    trans=Counter()

    for i in range(len(g)-1):

        if g[i]==cur:

            trans[g[i+1]]+=1

    total=sum(trans.values())

    if total<50:
        return None

    pred=max(trans,key=trans.get)

    prob=trans[pred]/total

    se=math.sqrt(0.25*0.75/total)

    z=(prob-0.25)/se

    if abs(z)>2:

        return pred

    return None

# ---------- ensemble ----------
def ensemble(g):

    signals=[]

    p=pattern_bias(g)
    t=transition_bias(g)

    if p:
        signals.append(p)

    if t:
        signals.append(t)

    if len(signals)>=2:

        return Counter(signals).most_common(1)[0][0]

    return None

# ---------- backtest ----------
profit=0
history=[]

for i in range(500,len(groups)-1):

    g=groups[i-500:i]

    pred=ensemble(g)

    hit=False

    if pred:

        if groups[i]==pred:

            profit+=2.5
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

hist=pd.DataFrame(history)

# ---------- metrics ----------
trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0

ev=wr*2.5-(1-wr)

drawdown=(hist.profit.cummax()-hist.profit).max()

# ---------- UI ----------
st.title("⚡ V37 Ensemble Edge Engine")

c1,c2,c3,c4=st.columns(4)

c1.metric("Rounds",len(groups))
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))
c4.metric("EV",round(ev,3))

c5,c6,c7=st.columns(3)

c5.metric("Profit",round(profit,2))
c6.metric("Drawdown",round(drawdown,2))
c7.metric("Entropy",round(entropy(analysis),3))

# ---------- next ----------
st.subheader("Next Group")

pred=ensemble(analysis)

if pred:

    st.success(f"BET → {pred}")

else:

    st.info("SKIP")

# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(hist.profit)

# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(100))
