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

analysis=groups[-1000:]

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

    trans={}

    for i in range(len(g)-1):

        a=g[i]
        b=g[i+1]

        if a not in trans:

            trans[a]=Counter()

        trans[a][b]+=1

    max_bias=0

    for cur in trans:

        total=sum(trans[cur].values())

        if total<50:
            continue

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

    if not seq:
        return 0

    top=max(seq.values())

    avg=np.mean(list(seq.values()))

    return (top-avg)/avg

# ---------- runs bias ----------
def runs_bias(g):

    max_run=1
    run=1

    for i in range(1,len(g)):

        if g[i]==g[i-1]:

            run+=1

            max_run=max(max_run,run)

        else:

            run=1

    expected=math.log(len(g),4)

    return max(0,(max_run-expected)/expected)

# ---------- edge score ----------
dist=distribution_bias(analysis)
trans=transition_bias(analysis)
pattern=pattern_bias(analysis)
runs=runs_bias(analysis)

edge=(dist+trans+pattern+runs)/4

# ---------- UI ----------
st.title("🔎 V38 Casino Bias Scanner")

c1,c2,c3,c4=st.columns(4)

c1.metric("Entropy",round(entropy(analysis),3))
c2.metric("Chi-square",round(chi_square(analysis),2))
c3.metric("Distribution Bias",round(dist,3))
c4.metric("Transition Bias",round(trans,3))

c5,c6,c7=st.columns(3)

c5.metric("Pattern Bias",round(pattern,3))
c6.metric("Runs Bias",round(runs,3))
c7.metric("Edge Score",round(edge,3))

# ---------- classification ----------
st.subheader("Bias Classification")

if edge>0.7:

    st.error("🔥 Strong Bias Detected")

elif edge>0.5:

    st.warning("⚠️ Tradable Bias")

elif edge>0.3:

    st.info("Weak Bias")

else:

    st.success("Dataset appears Random")
