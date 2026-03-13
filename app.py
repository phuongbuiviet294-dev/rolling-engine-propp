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

ROUNDS=len(groups)

# ---------- MARKOV ----------
def markov_pred(g):

    if len(g)<2:return None

    last=g[-1]

    trans={1:Counter(),2:Counter(),3:Counter(),4:Counter()}

    for i in range(len(g)-1):

        trans[g[i]][g[i+1]]+=1

    if not trans[last]:

        return None

    return max(trans[last],key=trans[last].get)

# ---------- PATTERN ----------
def pattern_pred(g,L=3):

    if len(g)<L+1:return None

    key=tuple(g[-L:])

    counts=Counter()

    for i in range(len(g)-L):

        if tuple(g[i:i+L])==key:

            counts[g[i+L]]+=1

    if not counts:return None

    return max(counts,key=counts.get)

# ---------- TRANSITION ----------
def transition_pred(g):

    if len(g)<30:return None

    last=g[-1]

    nxt=g[-30:]

    c=Counter()

    for i in range(len(nxt)-1):

        if nxt[i]==last:

            c[nxt[i+1]]+=1

    if not c:return None

    return max(c,key=c.get)

# ---------- DISTRIBUTION ----------
def distribution_pred(g):

    w=g[-200:]

    c=Counter(w)

    expected=len(w)/4

    diff={k:expected-c[k] for k in [1,2,3,4]}

    return max(diff,key=diff.get)

# ---------- RUNS ----------
def runs_pred(g):

    if len(g)<3:return None

    if g[-1]==g[-2]:

        return np.random.choice([x for x in [1,2,3,4] if x!=g[-1]])

    return None

# ---------- VOTE ----------
engines={}

engines["markov"]=markov_pred(groups)
engines["pattern"]=pattern_pred(groups)
engines["transition"]=transition_pred(groups)
engines["distribution"]=distribution_pred(groups)
engines["runs"]=runs_pred(groups)

votes=Counter()

for e in engines.values():

    if e:

        votes[e]+=1

prediction=None
confidence=0

if votes:

    prediction=max(votes,key=votes.get)
    confidence=votes[prediction]/5

# ---------- BACKTEST ----------
profit=0
peak=0
dd=0
history=[]

for i in range(50,len(groups)-1):

    pred=prediction
    hit=False

    if pred:

        if groups[i]==pred:

            profit+=2.5
            hit=True

        else:

            profit-=1

    peak=max(peak,profit)
    dd=max(dd,peak-profit)

    history.append({
        "round":i,
        "actual":groups[i],
        "pred":pred,
        "hit":hit,
        "profit":profit
    })

hist=pd.DataFrame(history)

trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])
wr=wins/trades if trades else 0

entropy=-sum((groups.count(i)/len(groups))*np.log2(groups.count(i)/len(groups)) for i in [1,2,3,4])

# ---------- UI ----------

st.title("🤖 V47 Hybrid AI Engine")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",ROUNDS)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))

c4,c5,c6=st.columns(3)

c4.metric("Profit",profit)
c5.metric("Drawdown",dd)
c6.metric("Entropy",round(entropy,3))

# ---------- ENGINE VOTES ----------

st.subheader("Engine Predictions")

st.write(engines)

# ---------- NEXT GROUP ----------

st.subheader("Next Group")

if prediction and confidence>=0.35:

    st.success(f"TRADE → Group {prediction} (confidence {confidence:.2f})")

else:

    st.info("SKIP")

# ---------- EQUITY ----------

st.subheader("Equity Curve")

st.line_chart(hist.profit)

# ---------- HISTORY ----------

st.subheader("Trade History")

st.dataframe(hist.tail(100))
