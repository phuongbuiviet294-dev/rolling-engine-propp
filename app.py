import streamlit as st
import pandas as pd
from collections import Counter, defaultdict
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

# ---------- entropy ----------
def entropy(g):

    c=Counter(g)
    total=len(g)

    e=0
    for v in c.values():
        p=v/total
        e-=p*math.log2(p)

    return e

# ---------- chi-square ----------
def chi_square(g):

    c=Counter(g)
    total=len(g)

    expected=total/4

    chi=0

    for i in [1,2,3,4]:

        obs=c.get(i,0)

        chi+=(obs-expected)**2/expected

    return chi

# ---------- transition bias ----------
def transition_bias(g):

    trans=defaultdict(Counter)

    for i in range(len(g)-1):

        trans[g[i]][g[i+1]]+=1

    max_p=0

    for cur in trans:

        total=sum(trans[cur].values())

        if total<50:continue

        for nxt in [1,2,3,4]:

            p=trans[cur].get(nxt,0)/total

            max_p=max(max_p,abs(p-0.25))

    return max_p*4

# ---------- runs bias ----------
def runs_bias(g):

    run=1
    max_run=1

    for i in range(1,len(g)):

        if g[i]==g[i-1]:

            run+=1
            max_run=max(max_run,run)

        else:
            run=1

    expected=math.log(len(g),4)

    return max(0,(max_run-expected)/expected)

# ---------- edge ----------
def edge_score(g):

    e=entropy(g)
    chi=chi_square(g)
    trans=transition_bias(g)
    runs=runs_bias(g)

    dist=max(0,(chi-7.8)/10)

    entropy_bias=max(0,(2-e))

    edge=(0.4*trans + 0.3*dist + 0.2*entropy_bias + 0.1*runs)

    return edge,e,chi,trans,runs

# ---------- window scan ----------
WINDOWS=[300,500,800]

best_edge=0
best_window=None
best_start=0
best_metrics=None

for w in WINDOWS:

    for i in range(len(groups)-w):

        g=groups[i:i+w]

        edge,e,chi,trans,runs=edge_score(g)

        if edge>best_edge:

            best_edge=edge
            best_window=w
            best_start=i
            best_metrics=(e,chi,trans,runs)

segment=groups[best_start:best_start+best_window]

# ---------- prediction ----------
def predict_next(seg):

    trans=defaultdict(Counter)

    for i in range(len(seg)-1):

        trans[seg[i]][seg[i+1]]+=1

    last=seg[-1]

    if last not in trans:

        return "SKIP",0

    total=sum(trans[last].values())

    probs={g:trans[last][g]/total for g in [1,2,3,4]}

    pred=max(probs,key=probs.get)

    return pred,probs[pred]

pred,conf=predict_next(segment)

# ---------- UI ----------
st.title("🧠 V41 Professional RNG Analyzer")

c1,c2,c3=st.columns(3)

c1.metric("Best Window",best_window)
c2.metric("Start Index",best_start)
c3.metric("Edge Score",round(best_edge,3))

e,chi,trans,runs=best_metrics

c4,c5,c6,c7=st.columns(4)

c4.metric("Entropy",round(e,3))
c5.metric("Chi-square",round(chi,2))
c6.metric("Transition Bias",round(trans,3))
c7.metric("Runs Bias",round(runs,3))

st.subheader("Prediction")

if best_edge>0.5 and conf>0.65:

    st.success(f"Next Group: {pred}  (confidence {round(conf,3)})")

else:

    st.info("SKIP – No statistically significant bias")

# ---------- equity simulation ----------
equity=0
curve=[]

for i in range(best_start,best_start+best_window-1):

    pred,conf=predict_next(groups[:i])

    if conf>0.65:

        if pred==groups[i+1]:

            equity+=1
        else:

            equity-=1

    curve.append(equity)

st.subheader("Equity Curve (Selective Trades)")
st.line_chart(curve)
