import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# -------- group mapping --------
def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# -------- load data --------
@st.cache_data(ttl=5)
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers=load()
groups=[group(n) for n in numbers]

ROUNDS=len(groups)

# -------- ENTROPY --------
def entropy_calc(g):

    probs=[g.count(i)/len(g) for i in [1,2,3,4]]

    return -sum(p*np.log2(p) for p in probs if p>0)

entropy=entropy_calc(groups)

# -------- CHI SQUARE --------
def chi_square(g):

    c=Counter(g)

    exp=len(g)/4

    return sum((c[i]-exp)**2/exp for i in [1,2,3,4])

chi=chi_square(groups)

# -------- MARKOV BIAS --------
def markov_bias(g):

    trans={i:Counter() for i in [1,2,3,4]}

    for i in range(len(g)-1):

        trans[g[i]][g[i+1]]+=1

    bias=0

    for k in trans:

        total=sum(trans[k].values())

        if total>0:

            p=max(trans[k].values())/total

            bias=max(bias,p-0.25)

    return bias

markov=markov_bias(groups)

# -------- PATTERN STRENGTH --------
def pattern_strength(g,L=3):

    counts={}

    for i in range(len(g)-L):

        key=tuple(g[i:i+L])

        nxt=g[i+L]

        counts.setdefault(key,Counter())

        counts[key][nxt]+=1

    best=0

    for k in counts:

        total=sum(counts[k].values())

        if total>20:

            p=max(counts[k].values())/total

            best=max(best,p/0.25)

    return best

pattern=pattern_strength(groups)

# -------- EDGE SCORE --------
edge_score=(markov*2)+(pattern/2)+(chi/10)

# -------- PREDICTION --------
prediction=None
confidence=0

if entropy<1.98 and chi>2 and markov>0.08 and pattern>1.5:

    last=groups[-1]

    trans={i:Counter() for i in [1,2,3,4]}

    for i in range(len(groups)-1):

        trans[groups[i]][groups[i+1]]+=1

    if trans[last]:

        prediction=max(trans[last],key=trans[last].get)

        confidence=trans[last][prediction]/sum(trans[last].values())

# -------- BACKTEST --------
profit=0
peak=0
dd=0
history=[]

for i in range(50,len(groups)-1):

    pred=prediction
    hit=False

    if pred:

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

# -------- UI --------

st.title("🤖 V48 Edge Detection AI")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",ROUNDS)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))

c4,c5,c6=st.columns(3)

c4.metric("Profit",profit)
c5.metric("Drawdown",dd)
c6.metric("Entropy",round(entropy,3))

st.subheader("Edge Analysis")

st.write({
"chi_square":round(chi,3),
"markov_bias":round(markov,3),
"pattern_strength":round(pattern,3),
"edge_score":round(edge_score,3)
})

# -------- NEXT GROUP --------

st.subheader("Next Group")

if prediction:

    st.success(f"TRADE → Group {prediction} (confidence {confidence:.2f})")

else:

    st.info("SKIP — No statistical edge")

# -------- EQUITY --------

st.subheader("Equity Curve")

st.line_chart(hist.profit)

# -------- HISTORY --------

st.subheader("Trade History")

st.dataframe(hist.tail(100))
