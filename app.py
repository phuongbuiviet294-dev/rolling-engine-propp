import streamlit as st
import pandas as pd
from collections import Counter, defaultdict
import numpy as np

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

# ---------- Markov ----------
def markov_probs(seq,alpha=1):

    trans=defaultdict(Counter)

    for i in range(len(seq)-1):

        trans[seq[i]][seq[i+1]]+=1

    last=seq[-1]

    total=sum(trans[last].values())

    probs={}

    for g in [1,2,3,4]:

        probs[g]=(trans[last][g]+alpha)/(total+4*alpha)

    return probs

# ---------- adaptive window ----------
WINDOWS=[200,400,800]

best_window=None
best_conf=0
best_pred=None
best_probs=None

for w in WINDOWS:

    seq=groups[-w:]

    probs=markov_probs(seq)

    pred=max(probs,key=probs.get)

    conf=probs[pred]

    if conf>best_conf:

        best_conf=conf
        best_pred=pred
        best_window=w
        best_probs=probs

edge=best_conf-0.25

# ---------- Kelly ----------
def kelly(edge):

    if edge<=0:return 0

    return edge/(1-edge)

kelly_frac=kelly(edge)

# ---------- UI ----------
st.title("🤖 V42 Adaptive Markov AI")

c1,c2,c3=st.columns(3)

c1.metric("Best Window",best_window)

c2.metric("Prediction",best_pred)

c3.metric("Confidence",round(best_conf,3))

c4,c5=st.columns(2)

c4.metric("Edge",round(edge,3))

c5.metric("Kelly Fraction",round(kelly_frac,3))

st.subheader("Probability Distribution")

prob_df=pd.DataFrame.from_dict(best_probs,orient="index",columns=["prob"])

st.bar_chart(prob_df)

# ---------- trade signal ----------
if best_conf>=0.65 and edge>=0.15:

    st.success(f"TRADE: Bet Group {best_pred}")

else:

    st.info("SKIP – Edge too small")

# ---------- equity simulation ----------
equity=0
curve=[]

for i in range(800,len(groups)-1):

    seq=groups[i-800:i]

    probs=markov_probs(seq)

    pred=max(probs,key=probs.get)

    conf=probs[pred]

    edge=conf-0.25

    if conf>=0.65 and edge>=0.15:

        if pred==groups[i]:

            equity+=1

        else:

            equity-=1

    curve.append(equity)

st.subheader("Equity Curve (Selective Trading)")

st.line_chart(curve)
