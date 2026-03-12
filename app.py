import streamlit as st
import pandas as pd
from collections import Counter, defaultdict

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

WINDOW=300
seq=groups[-WINDOW:]

# ---------- Markov ----------
def markov(seq):

    trans=defaultdict(Counter)

    for i in range(len(seq)-1):
        trans[seq[i]][seq[i+1]]+=1

    last=seq[-1]

    total=sum(trans[last].values())

    probs={g:(trans[last][g]+1)/(total+4) for g in [1,2,3,4]}

    return probs

# ---------- frequency ----------
def frequency(seq):

    c=Counter(seq)

    total=len(seq)

    return {g:c[g]/total for g in [1,2,3,4]}

# ---------- pattern ----------
def pattern(seq):

    patterns=defaultdict(Counter)

    for i in range(len(seq)-2):
        patterns[(seq[i],seq[i+1])][seq[i+2]]+=1

    last=(seq[-2],seq[-1])

    total=sum(patterns[last].values())

    if total==0:
        return {g:0.25 for g in [1,2,3,4]}

    return {g:(patterns[last][g]+1)/(total+4) for g in [1,2,3,4]}

# ---------- momentum ----------
def momentum(seq):

    last=seq[-1]

    streak=1

    for i in range(len(seq)-2,-1,-1):

        if seq[i]==last:
            streak+=1
        else:
            break

    probs={g:0.25 for g in [1,2,3,4]}

    if streak>=2:
        probs[last]+=0.15

    return probs

# ---------- engines ----------
p_markov=markov(seq)
p_freq=frequency(seq)
p_pattern=pattern(seq)
p_momentum=momentum(seq)

# ---------- ensemble ----------
final={}

for g in [1,2,3,4]:

    final[g]=(
        0.4*p_markov[g]
        +0.2*p_freq[g]
        +0.2*p_pattern[g]
        +0.2*p_momentum[g]
    )

pred=max(final,key=final.get)

conf=final[pred]

edge=conf-0.25

# ---------- UI ----------
st.title("🧠 V43 Ensemble AI Predictor")

c1,c2,c3=st.columns(3)

c1.metric("Prediction",pred)
c2.metric("Confidence",round(conf,3))
c3.metric("Edge",round(edge,3))

st.subheader("Engine Probabilities")

df=pd.DataFrame({
"Markov":p_markov,
"Frequency":p_freq,
"Pattern":p_pattern,
"Momentum":p_momentum,
"Final":final
})

st.bar_chart(df)

# ---------- trade signal ----------
if conf>=0.6 and edge>=0.1:

    st.success(f"TRADE Group {pred}")

else:

    st.info("SKIP – No edge")

# ---------- equity simulation ----------
equity=0
curve=[]

for i in range(WINDOW,len(groups)-1):

    seq=groups[i-WINDOW:i]

    p_markov=markov(seq)
    p_freq=frequency(seq)
    p_pattern=pattern(seq)
    p_momentum=momentum(seq)

    final={}

    for g in [1,2,3,4]:

        final[g]=(
            0.4*p_markov[g]
            +0.2*p_freq[g]
            +0.2*p_pattern[g]
            +0.2*p_momentum[g]
        )

    pred=max(final,key=final.get)

    conf=final[pred]

    if conf>=0.6:

        if pred==groups[i]:
            equity+=1
        else:
            equity-=1

    curve.append(equity)

st.subheader("Equity Curve")

st.line_chart(curve)
