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


# ---------- threshold ----------
def threshold(ent):

    if ent<1.97:
        return 0.42,"strong"

    if ent<1.99:
        return 0.36,"medium"

    return 0.32,"random"


# ---------- pattern ----------
def pattern_edge(g):

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


# ---------- markov ----------
def markov_edge(g):

    if len(g)<40:return None,0

    cur=g[-1]

    trans={1:0,2:0,3:0,4:0}
    total=0

    for i in range(len(g)-1):

        if g[i]==cur:

            trans[g[i+1]]+=1
            total+=1

    if total<8:return None,0

    for k in trans:
        trans[k]/=total

    best=max(trans,key=trans.get)

    return best,trans[best]


# ---------- imbalance ----------
def imbalance_edge(g):

    window=g[-40:]
    c=Counter(window)

    expected=10
    diff={i:expected-c.get(i,0) for i in [1,2,3,4]}

    best=max(diff,key=diff.get)

    return best,diff[best]/10


# ---------- streak ----------
def streak_edge(g):

    if len(g)>=3 and g[-1]==g[-2]==g[-3]:

        for i in [1,2,3,4]:

            if i!=g[-1]:

                return i,0.25

    return None,0


# ---------- detect ----------
def detect_edge(g):

    score={1:0,2:0,3:0,4:0}

    p,sp=pattern_edge(g)
    m,sm=markov_edge(g)
    i,si=imbalance_edge(g)
    s,ss=streak_edge(g)

    if p:score[p]+=sp*0.35
    if m:score[m]+=sm*0.30
    if i:score[i]+=si*0.20
    if s:score[s]+=ss*0.15

    ranked=sorted(score.items(),key=lambda x:x[1],reverse=True)

    best,strength=ranked[0]
    second=ranked[1][1]

    th,reg=threshold(ent)

    if strength>th and (strength-second)>0.05:

        return best,strength,reg

    return None,0,reg


# ---------- backtest ----------
profit=0
history=[]

for i in range(200,len(groups)-1):

    g=groups[max(0,i-200):i]

    pred,strength,reg=detect_edge(g)

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
        "profit":profit,
        "strength":strength,
        "regime":reg
    })

hist=pd.DataFrame(history)


# ---------- metrics ----------
trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0
ev=wr*2.5-(1-wr)

drawdown=(hist.profit.cummax()-hist.profit).max()


# ---------- UI ----------
st.title("🚀 V29 AI EDGE ENGINE")

c1,c2,c3,c4=st.columns(4)

c1.metric("Rounds",len(groups))
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))
c4.metric("EV",round(ev,3))

c5,c6,c7=st.columns(3)

c5.metric("Profit",round(profit,2))
c6.metric("Drawdown",round(drawdown,2))
c7.metric("Entropy",round(ent,3))


# ---------- next group ----------
st.subheader("Next Group")

pred,strength,reg=detect_edge(analysis)

if pred:

    st.success(f"BET → {pred} | strength {round(strength,2)} | regime {reg}")

else:

    st.info(f"SKIP | regime {reg}")


# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(hist.profit)


# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(100))
