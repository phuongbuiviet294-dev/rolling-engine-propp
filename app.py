import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


@st.cache_data(ttl=3)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()
groups=[group(n) for n in numbers]


# ---------- SIGNALS ----------

def streak_signal(g):

    if len(g)<3:return None,0

    if g[-1]==g[-2]==g[-3]:

        score=3

        if len(g)>=4 and g[-4]==g[-1]:
            score=5

        return [x for x in [1,2,3,4] if x!=g[-1]],score

    return None,0


def imbalance_signal(g):

    if len(g)<40:return None,0

    window=g[-40:]
    c=Counter(window)

    for i in range(1,5):
        c.setdefault(i,0)

    exp=10

    diff={i:exp-c[i] for i in c}

    best=max(diff,key=diff.get)

    if diff[best]>=4:
        return [best],4

    return None,0


def cluster_signal(g):

    if len(g)<6:return None,0

    s=g[-6:]

    if s[0]==s[2]==s[4] and s[1]==s[3]==s[5]:

        return [s[-1],s[-2]],3

    return None,0


# ---------- EDGE ----------

def detect_edge(g):

    preds=[]
    score=0
    analysis={}

    p,s=streak_signal(g)
    analysis["streak"]=s
    if p:
        preds+=p
        score+=s

    p,s=imbalance_signal(g)
    analysis["imbalance"]=s
    if p:
        preds+=p
        score+=s

    p,s=cluster_signal(g)
    analysis["cluster"]=s
    if p:
        preds+=p
        score+=s

    analysis["score"]=score

    if score>=6:
        return list(set(preds)),analysis

    return None,analysis


# ---------- BACKTEST ----------

profit=0
history=[]

for i in range(60,len(groups)-1):

    g=groups[:i]

    pred,analysis=detect_edge(g)

    p=None
    hit=False

    if pred:

        p=np.random.choice(pred)

        if groups[i]==p:

            profit+=3
            hit=True

        else:

            profit-=1

    history.append({

        "round":i,
        "actual":groups[i],
        "pred":p,
        "score":analysis["score"],
        "hit":hit,
        "profit":profit

    })


hist=pd.DataFrame(history)

trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0


# ---------- UI ----------

st.title("🚀 V17 PRO Live Engine")

c1,c2,c3=st.columns(3)

c1.metric("Profit",profit)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))


# ---------- ANALYSIS ----------

st.subheader("Analysis Parameters")

pred,analysis=detect_edge(groups)

st.write(analysis)


# ---------- NEXT GROUP ----------

st.subheader("Next Group")

if pred:
    st.success(f"BET {pred}")

else:
    st.info("SKIP")


# ---------- EQUITY ----------

st.subheader("Equity Curve")

st.line_chart(hist.profit)


# ---------- HISTORY ----------

st.subheader("Trade History")

st.dataframe(hist.tail(50))


# ---------- RECENT GROUPS ----------

st.subheader("Recent Groups")

st.write(groups[-20:])
