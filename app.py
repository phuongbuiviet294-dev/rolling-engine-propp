import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1

TRAIN_STEP=400
TRADE_STEP=400

LOOKBACK_RANGE=range(20,33)
GAP_RANGE=range(3,6)

WINDOW=9

st.set_page_config(layout="wide")
st.title("🚀 LIVE WALK FORWARD ENGINE")

def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

@st.cache_data
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers=load()

# ---------------------------
# SIGNAL
# ---------------------------

def signal(data,lookback):

    if len(data)<lookback:
        return None

    seq=[]

    start=max(WINDOW,len(data)-lookback)

    for j in range(start,len(data)):

        if j>=WINDOW:

            seq.append(
                1 if group(data[j])==group(data[j-WINDOW]) else 0
            )

    if len(seq)<10:
        return None

    wr=np.mean(seq)

    ev=wr*WIN-(1-wr)*LOSS

    if ev>0:

        g1=group(data[-WINDOW])

        if group(data[-1])!=g1:
            return g1

    return None


# ---------------------------
# OPTIMIZE
# ---------------------------

def optimize(train):

    best=-999
    best_cfg=(26,4)

    for LB in LOOKBACK_RANGE:

        for GP in GAP_RANGE:

            profit=0
            last=-999

            for i in range(len(train)):

                if i-last<GP:
                    continue

                vote=signal(train[:i],LB)

                if vote is None:
                    continue

                g=group(train[i])

                if vote==g:
                    profit+=WIN
                else:
                    profit-=LOSS

                last=i

            if profit>best:

                best=profit
                best_cfg=(LB,GP)

    return best_cfg


# ---------------------------
# WALK FORWARD
# ---------------------------

profit=0
engine=[]

train_end=TRAIN_STEP

while train_end+TRADE_STEP<=len(numbers):

    train=numbers[:train_end]

    LB,GP=optimize(train)

    trade=numbers[train_end:train_end+TRADE_STEP]

    last_trade=-999
    next_signal=None

    for i,n in enumerate(trade):

        g=group(n)

        predicted=None
        hit=None
        state="SCAN"

        if next_signal is not None:

            predicted=next_signal
            hit=1 if predicted==g else 0

            profit+=WIN if hit else -LOSS

            state="TRADE"

            last_trade=i
            next_signal=None

        if i-last_trade>GP:

            vote=signal(trade[:i],LB)

            if vote:
                next_signal=vote
                state="SIGNAL"

        engine.append({
            "round":train_end+i,
            "number":n,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":profit
        })

    train_end+=TRADE_STEP


# ---------------------------
# NEXT GROUP
# ---------------------------

LB,GP=optimize(numbers)

next_group=signal(numbers,LB)

# ---------------------------
# METRICS
# ---------------------------

hits=[x["hit"] for x in engine if x["hit"]!=None]

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
losses=hits.count(0)*LOSS

pf=wins/losses if losses else 0

profits=[x["profit"] for x in engine]

peak=max(profits) if profits else 0
dd=peak-profits[-1] if profits else 0

# ---------------------------
# DASHBOARD
# ---------------------------

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("PF",round(pf,2))

c4,c5=st.columns(2)

c4.metric("Drawdown",round(dd,2))
c5.metric("Trades",len(hits))

# ---------------------------
# SIGNAL
# ---------------------------

if next_group:

    st.markdown(
        f"""
        <div style='padding:20px;background:#c62828;color:white;
        border-radius:12px;text-align:center;font-size:30px;font-weight:bold'>
        NEXT GROUP: {next_group}
        </div>
        """,
        unsafe_allow_html=True
    )

else:

    st.info("Scanning...")

# ---------------------------
# EQUITY
# ---------------------------

st.line_chart(pd.DataFrame(profits))

# ---------------------------
# HISTORY
# ---------------------------

st.dataframe(pd.DataFrame(engine).iloc[::-1])
