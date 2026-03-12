import streamlit as st
import pandas as pd
import numpy as np
import requests, io
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW=9
LOOKBACK=26
GAP=4

WIN=3
LOSS=1

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

    r=requests.get(DATA_URL)

    df=pd.read_csv(io.StringIO(r.text))

    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

# ---------- simulate ----------
profit=0
history=[]
equity=[]

last_trade=-999
next_signal=None

for i in range(len(groups)):

    g=groups[i]

    predicted=None
    hit=None

    if next_signal is not None:

        predicted=next_signal

        hit=1 if predicted==g else 0

        if hit:
            profit+=WIN
        else:
            profit-=LOSS

        next_signal=None
        last_trade=i

    if i-last_trade>GAP and i>LOOKBACK:

        rec=[]

        for j in range(max(WINDOW,i-LOOKBACK),i):

            if j>=WINDOW:

                rec.append(
                    1 if groups[j]==groups[j-WINDOW] else 0
                )

        if len(rec)>15:

            wr=np.mean(rec)

            ev=wr*WIN-(1-wr)*LOSS

            if wr>0.28 and ev>0:

                next_signal=groups[i-WINDOW]

    equity.append(profit)

    history.append({

        "round":i+1,
        "actual":g,
        "pred":predicted,
        "hit":hit,
        "profit":profit

    })

hist=pd.DataFrame(history)

# ---------- metrics ----------
trades=len(hist[hist.pred.notna()])
wins=len(hist[hist.hit==1])

wr=wins/trades if trades else 0

losses=trades-wins

pf=(wins*WIN)/(losses*LOSS) if losses else 0

drawdown=max(equity)-min(equity)

ev=wr*WIN-(1-wr)*LOSS

# ---------- UI ----------
st.title("🚀 V19 Quant Dashboard")

c1,c2,c3,c4,c5,c6=st.columns(6)

c1.metric("Profit",profit)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))
c4.metric("Profit Factor",round(pf,2))
c5.metric("Drawdown",drawdown)
c6.metric("EV",round(ev,3))

# ---------- parameters ----------
st.subheader("Engine Parameters")

st.write({

"Window":WINDOW,
"Lookback":LOOKBACK,
"Gap":GAP

})

# ---------- next signal ----------
st.subheader("Next Group")

if next_signal:

    st.success(f"NEXT GROUP → {next_signal}")

else:

    st.info("Scanning...")

# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(equity)

# ---------- history ----------
st.subheader("Trade History")

st.dataframe(hist.tail(50))

# ---------- distribution ----------
st.subheader("Group Distribution")

dist=Counter(groups)

df=pd.DataFrame({

"group":dist.keys(),
"count":dist.values()

})

st.bar_chart(df.set_index("group"))
