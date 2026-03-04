import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5
LOOKBACK=100

st.set_page_config(layout="wide")

def get_group(n):
    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4
    return None

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df=load()
numbers=df["number"].dropna().astype(int).tolist()

engine=[]
profit=0

for i,n in enumerate(numbers):

    g=get_group(n)

    predicted_weak=None
    state="SCAN"
    hit=None

    if len(engine)>=LOOKBACK:

        recent=[x["group"] for x in engine[-LOOKBACK:]]

        freq={k:recent.count(k) for k in [1,2,3,4]}

        weak=min(freq,key=freq.get)

        predicted_weak=weak

        # bet 3 group còn lại
        if g==weak:
            profit-=3
            hit=0
        else:
            profit+=0.5
            hit=1

        state="TRADE"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "weak_group":predicted_weak,
        "hit":hit,
        "state":state
    })

st.title("🛡️ ANTI GROUP ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",len(engine))
c2.metric("Profit",round(profit,2))

hits=[x["hit"] for x in engine if x["hit"]!=None]

if hits:
    wr=np.mean(hits)
    c3.metric("Winrate %",round(wr*100,2))

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
