import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1

LOOKBACK=26
GAP=4
WINDOW=9

st.set_page_config(layout="wide")
st.title("🚀 LIVE TRADING ENGINE")

# -------------------------
# GROUP
# -------------------------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# -------------------------
# LOAD DATA
# -------------------------

@st.cache_data(ttl=10)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()

# -------------------------
# ENGINE
# -------------------------

profit=0
engine=[]
next_signal=None
last_trade=-999

for i,n in enumerate(numbers):

    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    # execute trade
    if next_signal is not None:

        predicted=next_signal

        hit=1 if predicted==g else 0

        profit += WIN if hit else -LOSS

        state="TRADE"

        last_trade=i
        next_signal=None

    # signal scan
    if i-last_trade>GAP and i>LOOKBACK:

        seq=[]

        start=max(WINDOW,i-LOOKBACK)

        for j in range(start,i):

            if j>=WINDOW:

                seq.append(
                    1 if group(numbers[j])==group(numbers[j-WINDOW]) else 0
                )

        if len(seq)>10:

            wr=np.mean(seq)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(numbers[i-WINDOW])

                if group(numbers[i-1])!=g1:

                    next_signal=g1
                    state="SIGNAL"

    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state,
        "profit":profit

    })

# -------------------------
# METRICS
# -------------------------

hits=[x["hit"] for x in engine if x["hit"]!=None]

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
losses=hits.count(0)*LOSS

pf=wins/losses if losses else 0

profits=[x["profit"] for x in engine]

peak=max(profits) if profits else 0

dd=peak-profits[-1] if profits else 0

# -------------------------
# DASHBOARD
# -------------------------

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5=st.columns(2)

c4.metric("Drawdown",round(dd,2))
c5.metric("Trades",len(hits))

# -------------------------
# SIGNAL
# -------------------------

if next_signal:

    st.markdown(

        f"""
        <div style='padding:25px;background:#c62828;color:white;
        border-radius:12px;text-align:center;font-size:30px;font-weight:bold'>
        NEXT GROUP: {next_signal}
        </div>
        """,

        unsafe_allow_html=True

    )

else:

    st.info("Scanning...")

# -------------------------
# EQUITY
# -------------------------

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame(profits))

# -------------------------
# HISTORY
# -------------------------

st.subheader("History")

hist=pd.DataFrame(engine)

st.dataframe(hist.iloc[::-1],use_container_width=True)
