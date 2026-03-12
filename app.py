import streamlit as st
import pandas as pd
import requests
import io
from collections import Counter
import random

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# ---------- group mapping ----------
def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ---------- load data ----------
@st.cache_data(ttl=3)
def load():
    r=requests.get(DATA_URL)
    df=pd.read_csv(io.StringIO(r.text))
    df.columns=[c.lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers=load()
groups=[group(n) for n in numbers]

# ---------- signals ----------
def streak_signal(g):
    if len(g)<3:return None,0
    if g[-1]==g[-2]==g[-3]:
        return [x for x in [1,2,3,4] if x!=g[-1]],3
    return None,0

def imbalance_signal(g):
    if len(g)<40:return None,0
    w=g[-40:]
    c=Counter(w)
    for i in range(1,5): c.setdefault(i,0)
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

def detect_edge(g):
    preds=[]
    score=0
    for fn in [streak_signal,imbalance_signal,cluster_signal]:
        p,s=fn(g)
        if p:
            preds+=p
            score+=s
    if score>=6:
        return list(set(preds)),score
    return None,score

# ---------- session state ----------
if "last_round" not in st.session_state:
    st.session_state.last_round=len(groups)
    st.session_state.profit=0
    st.session_state.trades=0
    st.session_state.wins=0
    st.session_state.history=[]

# ---------- detect new round ----------
current_round=len(groups)

if current_round>st.session_state.last_round:

    new_group=groups[-1]

    pred,score=detect_edge(groups[:-1])

    hit=False

    if pred:
        choice=random.choice(pred)
        st.session_state.trades+=1

        if new_group==choice:
            st.session_state.wins+=1
            st.session_state.profit+=3
            hit=True
        else:
            st.session_state.profit-=1

        st.session_state.history.append({
            "round":current_round,
            "actual":new_group,
            "pred":choice,
            "hit":hit,
            "profit":st.session_state.profit
        })

    st.session_state.last_round=current_round

# ---------- metrics ----------
wr=st.session_state.wins/st.session_state.trades if st.session_state.trades else 0

st.title("🚀 V18 PRO Live Quant Engine")

c1,c2,c3=st.columns(3)

c1.metric("Profit",st.session_state.profit)
c2.metric("Trades",st.session_state.trades)
c3.metric("Winrate",round(wr*100,2))

# ---------- next signal ----------
pred,score=detect_edge(groups)

st.subheader("Next Group")

if pred:
    st.success(f"BET {pred} | score {score}")
else:
    st.info("SKIP")

# ---------- recent groups ----------
st.subheader("Recent Groups")
st.write(groups[-20:])

# ---------- history ----------
if st.session_state.history:
    st.subheader("Trade History")
    st.dataframe(pd.DataFrame(st.session_state.history).tail(20))

# ---------- distribution ----------
dist=Counter(groups)
df=pd.DataFrame({"group":dist.keys(),"count":dist.values()})

st.subheader("Group Distribution")
st.bar_chart(df.set_index("group"))
