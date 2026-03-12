import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
import math

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# ---------------- GROUP ----------------

def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# ---------------- LOAD DATA ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    nums=df["number"].dropna().astype(int).tolist()

    return nums

numbers=load()

groups=[group(n) for n in numbers]


# ---------------- ENTROPY ----------------

def entropy(g):

    c=Counter(g)

    total=len(g)

    e=0

    for v in c.values():

        p=v/total

        e-=p*math.log2(p)

    return e

ent=entropy(groups)


# ---------------- DISTRIBUTION ----------------

dist=Counter(groups)

dist_df=pd.DataFrame({

"group":list(dist.keys()),
"count":list(dist.values())
})

dist_df["ratio"]=dist_df["count"]/len(groups)


# ---------------- MARKOV MATRIX ----------------

def markov(g):

    trans={}

    for i in range(len(g)-1):

        a=g[i]
        b=g[i+1]

        trans.setdefault(a,[])
        trans[a].append(b)

    probs={}

    for k,v in trans.items():

        c=Counter(v)

        total=sum(c.values())

        probs[k]={i:c.get(i,0)/total for i in [1,2,3,4]}

    return probs

markov_matrix=markov(groups)


# ---------------- EDGE DETECT ----------------

def detect_edge(g):

    score={1:0,2:0,3:0,4:0}

    # streak
    if len(g)>=3 and g[-1]==g[-2]==g[-3]:

        for i in [1,2,3,4]:

            if i!=g[-1]:

                score[i]+=0.3

    # imbalance
    if len(g)>=40:

        window=g[-40:]

        c=Counter(window)

        for i in [1,2,3,4]:

            score[i]+=max(0,(10-c.get(i,0)))*0.02

    # markov
    last=g[-1]

    if last in markov_matrix:

        for i,p in markov_matrix[last].items():

            score[i]+=p*0.3

    best=max(score,key=score.get)

    strength=score[best]

    if strength>0.35:

        return best,strength

    return None,None


# ---------------- BACKTEST ----------------

profit=0

history=[]

for i in range(60,len(groups)-1):

    g=groups[:i]

    pred,strength=detect_edge(g)

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


# ---------------- METRICS ----------------

trades=len(hist[hist.pred.notna()])

wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0

ev=wr*2.5-(1-wr)*1

drawdown=(hist.profit.cummax()-hist.profit).max()


# ---------------- UI ----------------

st.title("🚀 V21 QUANT ENGINE")


col1,col2,col3,col4=st.columns(4)

col1.metric("Rounds",len(groups))
col2.metric("Trades",trades)
col3.metric("Winrate %",round(wr*100,2))
col4.metric("EV",round(ev,3))


col5,col6,col7=st.columns(3)

col5.metric("Profit",round(profit,2))
col6.metric("Drawdown",round(drawdown,2))
col7.metric("Entropy",round(ent,3))


# ---------------- NEXT GROUP ----------------

st.subheader("Next Group")

pred,strength=detect_edge(groups)

if pred:

    st.success(f"BET → {pred}  (strength {round(strength,2)})")

else:

    st.info("SKIP")


# ---------------- DISTRIBUTION ----------------

st.subheader("Group Distribution")

st.dataframe(dist_df)

st.bar_chart(dist_df.set_index("group")["ratio"])


# ---------------- MARKOV ----------------

st.subheader("Markov Transition")

mk=pd.DataFrame(markov_matrix).T

st.dataframe(mk)


# ---------------- EQUITY ----------------

st.subheader("Equity Curve")

st.line_chart(hist.profit)


# ---------------- HISTORY ----------------

st.subheader("Trade History")

st.dataframe(hist.tail(100))
