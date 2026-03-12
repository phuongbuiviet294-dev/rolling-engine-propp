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

analysis=groups[-300:]

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

# ---------- markov dependency ----------
def markov_bias(g):

    trans={}

    for i in range(len(g)-1):

        a=g[i]
        b=g[i+1]

        if a not in trans:

            trans[a]=Counter()

        trans[a][b]+=1

    bias=0

    for k,v in trans.items():

        total=sum(v.values())

        if total<20:
            continue

        probs=[x/total for x in v.values()]

        bias+=max(probs)-0.25

    return bias

# ---------- pattern bias ----------
def pattern_bias(g):

    seq=Counter()

    for i in range(len(g)-3):

        seq[tuple(g[i:i+3])] +=1

    if not seq:
        return 0

    top=max(seq.values())

    avg=np.mean(list(seq.values()))

    return (top-avg)/avg

# ---------- edge score ----------
def edge_score(g):

    e=entropy(g)
    chi=chi_square(g)
    mb=markov_bias(g)
    pb=pattern_bias(g)

    entropy_bias=max(0,2-e)

    chi_bias=chi/10

    score=0.3*entropy_bias+0.3*chi_bias+0.2*mb+0.2*pb

    return score,e,chi,mb,pb

# ---------- next group ----------
def next_group(g):

    c=Counter(g[-50:])

    best=max(c,key=c.get)

    return best

# ---------- backtest ----------
profit=0
history=[]

for i in range(300,len(groups)-1):

    g=groups[i-300:i]

    score,e,chi,mb,pb=edge_score(g)

    pred=None
    hit=False

    if score>0.55:

        pred=next_group(g)

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
        "profit":profit,
        "edge":score
    })

hist=pd.DataFrame(history)

# ---------- metrics ----------
trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0

ev=wr*2.5-(1-wr)

drawdown=(hist.profit.cummax()-hist.profit).max()

score,e,chi,mb,pb=edge_score(analysis)

# ---------- UI ----------
st.title("🧠 V34 RNG Detector Engine")

c1,c2,c3,c4=st.columns(4)

c1.metric("Rounds",len(groups))
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))
c4.metric("EV",round(ev,3))

c5,c6,c7=st.columns(3)

c5.metric("Profit",round(profit,2))
c6.metric("Drawdown",round(drawdown,2))
c7.metric("Edge Score",round(score,3))

st.subheader("Randomness Tests")

r1,r2,r3,r4=st.columns(4)

r1.metric("Entropy",round(e,3))
r2.metric("Chi-square",round(chi,2))
r3.metric("Markov Bias",round(mb,3))
r4.metric("Pattern Bias",round(pb,3))

# ---------- next ----------
st.subheader("Next Group")

if score>0.55:

    st.success(f"BET → {next_group(analysis)}")

else:

    st.info("SKIP")

# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(hist.profit)

# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(100))
