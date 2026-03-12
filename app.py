import streamlit as st
import pandas as pd
import numpy as np
from collections import defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1
GAP=4

PROB_THRESHOLD=0.35

st.set_page_config(layout="wide")

def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

@st.cache_data(ttl=5)
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

# ---------- build Markov table ----------

trans=defaultdict(lambda:defaultdict(int))

for i in range(2,len(groups)):
    
    key=(groups[i-2],groups[i-1])
    nxt=groups[i]
    
    trans[key][nxt]+=1


# ---------- engine ----------

profit=0
equity=[]
hits=[]
history=[]

last_trade=-999
next_signal=None

for i in range(len(groups)):

    g=groups[i]

    predicted=None
    hit=None

    # trade
    
    if next_signal and i-last_trade>=GAP:

        predicted=next_signal
        
        hit=(g==predicted)

        profit+=WIN if hit else -LOSS

        hits.append(hit)

        last_trade=i

        next_signal=None


    # predict

    if i>=2:

        key=(groups[i-2],groups[i-1])

        if key in trans:

            counts=trans[key]

            total=sum(counts.values())

            probs={k:v/total for k,v in counts.items()}

            best=max(probs,key=probs.get)

            p=probs[best]

            ev=p*WIN-(1-p)*LOSS

            if p>=PROB_THRESHOLD and ev>0:

                next_signal=best


    equity.append(profit)

    history.append({
        "round":i+1,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit":profit
    })


# ---------- analytics ----------

wins=hits.count(True)*WIN
losses=hits.count(False)*LOSS

pf=wins/losses if losses else 0
wr=sum(hits)/len(hits) if hits else 0

eq=np.array(equity)
peak=np.maximum.accumulate(eq)
drawdown=(peak-eq).max()

st.title("🚀 QUANT ENGINE V13 – Markov")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(drawdown,2))
c5.metric("Trades",len(hits))
c6.metric("Signal Threshold",PROB_THRESHOLD)

st.subheader("Equity Curve")
st.line_chart(pd.DataFrame({"profit":equity}))

st.subheader("Next Group")

if next_signal:

    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
    border-radius:12px;text-align:center;font-size:32px'>
    NEXT GROUP → {next_signal}
    </div>
    """,unsafe_allow_html=True)

else:
    st.info("Scanning...")

st.subheader("History")
st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
