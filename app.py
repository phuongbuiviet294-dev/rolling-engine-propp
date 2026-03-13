import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter,defaultdict

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

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

ROUNDS=len(groups)

# ---------- entropy ----------
def entropy(g):

    c=Counter(g)

    total=len(g)

    e=0

    for v in c.values():

        p=v/total

        e-=p*np.log2(p)

    return e

# ---------- distribution bias ----------
def distribution_bias(g):

    c=Counter(g)

    total=len(g)

    p=max(c.values())/total

    return p

# ---------- transition anomaly ----------
def transition_bias(g):

    if len(g)<2:return 0

    trans=defaultdict(list)

    for i in range(len(g)-1):

        trans[g[i]].append(g[i+1])

    last=g[-1]

    if last not in trans:return 0

    c=Counter(trans[last])

    total=sum(c.values())

    p=max(c.values())/total

    return p

# ---------- predictor ----------
def predict(g):

    c=Counter(g[-30:])

    return max(c,key=c.get)

# ---------- backtest ----------
profit=0
peak=0
dd=0

trades=0
wins=0

history=[]

for i in range(60,ROUNDS-1):

    g=groups[:i]

    e=entropy(g[-30:])

    bias=distribution_bias(g[-30:])

    trans=transition_bias(g)

    edge=0

    if e<1.85: edge+=1
    if bias>0.35: edge+=1
    if trans>0.45: edge+=1

    trade=False

    if edge>=2:

        trade=True

    pred=predict(g)

    actual=groups[i]

    hit=1 if pred==actual else 0

    if trade:

        trades+=1

        if hit:

            profit+=2.5
            wins+=1

        else:

            profit-=1

    peak=max(peak,profit)

    dd=max(dd,peak-profit)

    history.append({

        "round":i,
        "edge":edge,
        "pred":pred,
        "actual":actual,
        "trade":trade,
        "hit":hit,
        "profit":profit
    })

wr=wins/trades if trades else 0

hist_df=pd.DataFrame(history)

# ---------- live ----------
g=groups

edge=0

if entropy(g[-30:])<1.85: edge+=1
if distribution_bias(g[-30:])>0.35: edge+=1
if transition_bias(g)>0.45: edge+=1

live_pred=predict(g)

# ---------- UI ----------
st.title("🧠 V53 Edge Detection AI")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",ROUNDS)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))

c4,c5=st.columns(2)

c4.metric("Profit",profit)
c5.metric("Drawdown",dd)

st.subheader("Next Group")

if edge>=2:

    st.success(f"TRADE → Group {live_pred} (edge {edge})")

else:

    st.info("SKIP")

st.subheader("Equity Curve")

st.line_chart(hist_df["profit"])

st.subheader("History")

st.dataframe(hist_df.tail(100))
