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

# ---------- distribution bias ----------
def distribution_bias(g):
    c=Counter(g)
    total=len(g)
    max_bias=0
    for i in [1,2,3,4]:
        p=c.get(i,0)/total
        bias=abs(p-0.25)
        max_bias=max(max_bias,bias)
    return max_bias*4

# ---------- transition bias ----------
def transition_bias(g):
    trans=defaultdict(Counter)
    for i in range(len(g)-1):
        trans[g[i]][g[i+1]]+=1

    max_bias=0
    for cur in trans:
        total=sum(trans[cur].values())
        if total<30:continue
        for nxt in [1,2,3,4]:
            p=trans[cur].get(nxt,0)/total
            bias=abs(p-0.25)
            max_bias=max(max_bias,bias)
    return max_bias*4

# ---------- pattern bias ----------
def pattern_bias(g):
    seq=Counter()
    for i in range(len(g)-2):
        seq[(g[i],g[i+1],g[i+2])]+=1
    if not seq:return 0
    top=max(seq.values())
    avg=np.mean(list(seq.values()))
    return max(0,(top-avg)/avg)

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
    d=distribution_bias(g)
    t=transition_bias(g)
    p=pattern_bias(g)
    r=runs_bias(g)
    return (d+t+p+r)/4,d,t,p,r

# ---------- sliding window scan ----------
WINDOWS=[200,300,400,500]

best_edge=0
best_window=None
best_start=None
best_metrics=None

for w in WINDOWS:
    for i in range(len(groups)-w):
        g=groups[i:i+w]
        edge,d,t,p,r=edge_score(g)

        if edge>best_edge:
            best_edge=edge
            best_window=w
            best_start=i
            best_metrics=(d,t,p,r)

# ---------- best segment ----------
segment=groups[best_start:best_start+best_window]

# ---------- next prediction ----------
def predict_next(seg):

    last=seg[-1]

    trans=defaultdict(Counter)

    for i in range(len(seg)-1):
        trans[seg[i]][seg[i+1]]+=1

    if last not in trans:
        return "SKIP",0

    total=sum(trans[last].values())

    probs={g:trans[last][g]/total for g in [1,2,3,4]}

    pred=max(probs,key=probs.get)

    return pred,probs[pred]

pred,conf=predict_next(segment)

# ---------- UI ----------
st.title("🎯 V40 Window Bias Hunter")

st.subheader("Best Bias Window")

c1,c2,c3=st.columns(3)

c1.metric("Window Size",best_window)
c2.metric("Start Index",best_start)
c3.metric("Edge Score",round(best_edge,3))

d,t,p,r=best_metrics

c4,c5,c6,c7=st.columns(4)

c4.metric("Distribution Bias",round(d,3))
c5.metric("Transition Bias",round(t,3))
c6.metric("Pattern Bias",round(p,3))
c7.metric("Runs Bias",round(r,3))

st.subheader("Next Group Prediction")

if best_edge>=0.5:
    st.success(f"Next Group: {pred}  (confidence {round(conf,3)})")
else:
    st.info("SKIP — no strong bias detected")

# ---------- equity simulation ----------
equity=0
curve=[]

for i in range(best_start,best_start+best_window-1):

    if groups[i+1]==groups[i]:
        equity+=1
    else:
        equity-=1

    curve.append(equity)

st.subheader("Equity Curve (Best Window)")
st.line_chart(curve)
