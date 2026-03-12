import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# ---------------- group ----------------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------------- load ----------------

@st.cache_data(ttl=3)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()
groups=[group(n) for n in numbers]


# ---------------- edge signals ----------------

def streak_score(g):

    if len(g)<3:return None,0

    if g[-1]==g[-2]==g[-3]:

        return [x for x in [1,2,3,4] if x!=g[-1]],3

    return None,0


def imbalance_score(g):

    if len(g)<40:return None,0

    window=g[-40:]

    count=Counter(window)

    for i in range(1,5):

        count.setdefault(i,0)

    expected=10

    diff={i:expected-count[i] for i in count}

    best=max(diff,key=diff.get)

    if diff[best]>=4:

        return [best],4

    return None,0


def cluster_score(g):

    if len(g)<6:return None,0

    seq=g[-6:]

    if seq[0]==seq[2]==seq[4] and seq[1]==seq[3]==seq[5]:

        return [seq[-1],seq[-2]],3

    return None,0


# ---------------- edge detector ----------------

def detect_edge(g):

    signals=[]

    score=0

    for fn in [streak_score,imbalance_score,cluster_score]:

        pred,s=fn(g)

        if pred:

            signals+=pred
            score+=s

    if score>=5:

        return list(set(signals)),score

    return None,score


# ---------------- backtest ----------------

profit=0
equity=[]
history=[]

for i in range(60,len(groups)-1):

    g=groups[:i]

    pred,score=detect_edge(g)

    bet=0
    hit=False
    p=None

    if pred:

        p=np.random.choice(pred)

        if score>=9:bet=3
        elif score>=7:bet=2
        else:bet=1

        if groups[i]==p:

            profit+=bet*3
            hit=True

        else:

            profit-=bet

    equity.append(profit)

    history.append({
        "round":i,
        "actual":groups[i],
        "pred":p,
        "score":score,
        "hit":hit,
        "profit":profit
    })


hist=pd.DataFrame(history)

# ---------------- metrics ----------------

trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0


# ---------------- UI ----------------

st.title("🚀 V16 PRO Adaptive Engine")

c1,c2,c3=st.columns(3)

c1.metric("Profit",profit)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))


# ---------------- next group ----------------

pred,score=detect_edge(groups)

st.subheader("Next Group")

if pred:

    st.success(f"BET {pred} | score {score}")

else:

    st.info("SKIP")


# ---------------- equity ----------------

st.subheader("Equity Curve")

st.line_chart(equity)


# ---------------- history ----------------

st.subheader("History")

st.dataframe(hist.tail(50))


# ---------------- distribution ----------------

st.subheader("Distribution")

dist=Counter(groups)

df=pd.DataFrame({

    "group":dist.keys(),
    "count":dist.values()

})

st.bar_chart(df.set_index("group"))
