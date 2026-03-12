import streamlit as st
import pandas as pd
from collections import Counter
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

analysis=groups[-150:]


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


# ---------- pattern edge ----------
def pattern_edge(g):

    if len(g)<6:return None,0

    key=tuple(g[-3:])

    nexts=[]

    for i in range(len(g)-3):

        if tuple(g[i:i+3])==key:

            nexts.append(g[i+3])

    if len(nexts)<5:return None,0

    c=Counter(nexts)
    best=max(c,key=c.get)

    prob=c[best]/len(nexts)

    if prob>0.37:

        return best,prob

    return None,0


# ---------- imbalance ----------
def imbalance_edge(g):

    window=g[-40:]
    c=Counter(window)

    for i in [1,2,3,4]:

        if c.get(i,0)<=5:

            return i,0.3

    return None,0


# ---------- streak ----------
def streak_edge(g):

    if len(g)>=3 and g[-1]==g[-2]==g[-3]:

        for i in [1,2,3,4]:

            if i!=g[-1]:

                return i,0.25

    return None,0


# ---------- detect edge ----------
def detect_edge(g):

    score={1:0,2:0,3:0,4:0}
    source=[]

    p,sp=pattern_edge(g)

    if p:
        score[p]+=sp*0.45
        source.append("pattern")

    i,si=imbalance_edge(g)

    if i:
        score[i]+=si
        source.append("imbalance")

    s,ss=streak_edge(g)

    if s:
        score[s]+=ss
        source.append("streak")

    best=max(score,key=score.get)
    strength=score[best]

    if strength>0.65:

        return best,strength,",".join(source)

    return None,0,""


# ---------- backtest ----------
profit=0
history=[]

for i in range(200,len(groups)-1):

    g=groups[:i]

    pred,strength,edge=detect_edge(g)

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
st.title("🚀 V25 PRO LIVE ENGINE")

col1,col2,col3,col4=st.columns(4)

col1.metric("Rounds",len(groups))
col2.metric("Trades",trades)
col3.metric("Winrate %",round(wr*100,2))
col4.metric("EV",round(ev,3))

col5,col6,col7=st.columns(3)

col5.metric("Profit",round(profit,2))
col6.metric("Drawdown",round(drawdown,2))
col7.metric("Entropy",round(ent,3))


# ---------- next group ----------
st.subheader("Next Group")

pred,strength,edge=detect_edge(analysis)

if pred and ent<1.97:

    st.success(f"BET → {pred} | strength {round(strength,2)} | edge {edge}")

else:

    st.info("SKIP")


# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(hist.profit)


# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(100))
