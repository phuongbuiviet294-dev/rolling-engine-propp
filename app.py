import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter, defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# -------- GROUP --------
def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# -------- LOAD DATA --------
@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

ROUNDS=len(groups)

WINDOW=900

seq=groups[-WINDOW:]

# -------- PATTERN FUNCTION --------
def pattern_stats(data,L):

    patterns=defaultdict(Counter)

    for i in range(len(data)-L):

        key=tuple(data[i:i+L])
        nxt=data[i+L]

        patterns[key][nxt]+=1

    stats={}

    for key,count in patterns.items():

        total=sum(count.values())

        if total<20:
            continue

        pred=max(count,key=count.get)

        prob=count[pred]/total

        strength=prob/0.25

        stats[key]=(pred,prob,strength)

    return stats

# -------- STABILITY TEST --------

seg=len(seq)//3

seg1=seq[:seg]
seg2=seq[seg:2*seg]
seg3=seq[2*seg:]

best=None
best_score=0

for L in [3,4,5]:

    s1=pattern_stats(seg1,L)
    s2=pattern_stats(seg2,L)
    s3=pattern_stats(seg3,L)

    keys=set(s1)&set(s2)&set(s3)

    for k in keys:

        p1=s1[k]
        p2=s2[k]
        p3=s3[k]

        strength=min(p1[2],p2[2],p3[2])

        prob=(p1[1]+p2[1]+p3[1])/3

        if strength>best_score:

            best_score=strength
            best=(L,k,p1[0],prob,strength)

# -------- PREDICT --------
prediction=None
confidence=0
pattern=None
strength=0

if best:

    L,k,pred,prob,stren=best

    if tuple(groups[-L:])==k:

        prediction=pred
        confidence=prob
        pattern=k
        strength=stren

# -------- BACKTEST --------

profit=0
peak=0
dd=0
history=[]

for i in range(50,len(groups)-1):

    pred=None
    hit=False

    if prediction:

        pred=prediction

        if groups[i]==pred:

            profit+=2.5
            hit=True

        else:

            profit-=1

    peak=max(peak,profit)

    dd=max(dd,peak-profit)

    history.append({
        "round":i,
        "actual":groups[i],
        "pred":pred,
        "hit":hit,
        "profit":profit
    })

hist=pd.DataFrame(history)

trades=len(hist[hist.pred.notna()])

wins=len(hist[hist.hit==True])

wr=wins/trades if trades else 0

entropy=-sum((groups.count(i)/len(groups))*np.log2(groups.count(i)/len(groups)) for i in [1,2,3,4])

# -------- UI --------

st.title("🤖 V46 Live Pattern Stability Engine")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",ROUNDS)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))

c4,c5,c6=st.columns(3)

c4.metric("Profit",profit)
c5.metric("Drawdown",dd)
c6.metric("Entropy",round(entropy,3))

# -------- PATTERN --------

st.subheader("Pattern Analysis")

if pattern:

    st.write("Pattern:",pattern)
    st.write("Strength:",round(strength,3))
    st.write("Probability:",round(confidence,3))

# -------- NEXT GROUP --------

st.subheader("Next Group")

if prediction and strength>1.6 and confidence>0.40:

    st.success(f"TRADE → Group {prediction}")

else:

    st.info("SKIP")

# -------- EQUITY --------

st.subheader("Equity Curve")

st.line_chart(hist.profit)

# -------- HISTORY --------

st.subheader("Trade History")

st.dataframe(hist.tail(100))
