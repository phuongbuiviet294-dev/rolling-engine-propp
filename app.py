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

WINDOW=1200
seq=groups[-WINDOW:]

# ---------- pattern scan ----------
patterns=defaultdict(Counter)

for L in [3,4,5,6]:

    for i in range(len(seq)-L):

        key=tuple(seq[i:i+L])
        nxt=seq[i+L]

        patterns[(L,key)][nxt]+=1

best_pattern=None
best_strength=0
best_pred=None
best_prob=0

for (L,key),counts in patterns.items():

    total=sum(counts.values())

    if total<20:
        continue

    pred=max(counts,key=counts.get)

    prob=counts[pred]/total

    strength=prob/0.25

    if strength>best_strength:

        best_strength=strength
        best_pattern=(L,key)
        best_pred=pred
        best_prob=prob

# ---------- UI ----------
st.title("🔎 V45 Deep Pattern Hunter")

if best_pattern:

    L,key=best_pattern

    c1,c2,c3=st.columns(3)

    c1.metric("Pattern Length",L)
    c2.metric("Prediction",best_pred)
    c3.metric("Probability",round(best_prob,3))

    st.metric("Pattern Strength",round(best_strength,3))

    st.write("Pattern:",key)

else:

    st.write("No strong pattern detected")

# ---------- trade signal ----------
if best_strength>=1.5:

    st.success(f"TRADE Group {best_pred}")

else:

    st.info("SKIP – Pattern not strong enough")

# ---------- pattern frequency ----------
rows=[]

for (L,key),counts in patterns.items():

    total=sum(counts.values())

    if total<20:
        continue

    pred=max(counts,key=counts.get)

    prob=counts[pred]/total

    strength=prob/0.25

    rows.append([L,str(key),pred,prob,strength])

df=pd.DataFrame(rows,columns=["Length","Pattern","Prediction","Prob","Strength"])

st.subheader("Top Patterns")

st.dataframe(df.sort_values("Strength",ascending=False).head(20))
