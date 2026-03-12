import streamlit as st
import pandas as pd
import numpy as np

# =====================================
# CONFIG
# =====================================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN = 2.5
LOSS = 1

WINDOWS = [7,9,11,15]

LOOKBACK_RANGE = range(18,41)
GAP_RANGE = range(2,7)

TRAIN_SIZE = 2000
LIVE_SIZE = 400

STOPLOSS = 5
PAUSE_ROUNDS = 3

AUTO_REFRESH = 5

st.set_page_config(layout="wide")
st.title("🚀 QUANT LIVE TRADING ENGINE")

# =====================================
# GROUP
# =====================================

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# =====================================
# LOAD DATA
# =====================================

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int).tolist()

    return numbers

numbers=load()

# =====================================
# REGIME DETECTOR
# =====================================

def regime(data):

    if len(data)<50:return "UNKNOWN"

    seq=[]

    for i in range(20,len(data)):

        seq.append(
            1 if group(data[i])==group(data[i-9]) else 0
        )

    s=np.mean(seq)

    if s>0.55:return "TREND"
    if s<0.45:return "RANDOM"
    return "MEAN"

# =====================================
# SIGNAL ENGINE
# =====================================

def signal_engine(data,lookback,gap):

    scores=[]
    votes=[]

    for W in WINDOWS:

        if len(data)<lookback:continue

        seq=[]

        start=max(W,len(data)-lookback)

        for j in range(start,len(data)):

            if j>=W:

                seq.append(
                    1 if group(data[j])==group(data[j-W]) else 0
                )

        if len(seq)<15:continue

        wr=np.mean(seq)

        ev=wr*WIN-(1-wr)*LOSS

        if ev>0:

            g1=group(data[-W])

            if group(data[-1])!=g1:

                votes.append(g1)

                scores.append(ev)

    if not votes:

        return None,0

    vote=pd.Series(votes).mode()[0]

    edge=np.mean(scores)

    return vote,edge

# =====================================
# BACKTEST OPTIMIZER
# =====================================

def optimize(train):

    best=-999
    best_cfg=(26,4)

    for LB in LOOKBACK_RANGE:

        for GP in GAP_RANGE:

            profit=0
            last=-999

            for i in range(len(train)):

                if i-last<GP:continue

                vote,edge=signal_engine(train[:i],LB,GP)

                if vote is None:continue

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

# =====================================
# WALK FORWARD
# =====================================

train=numbers[-TRAIN_SIZE:]

LB,GP=optimize(train)

live=numbers[-LIVE_SIZE:]

# =====================================
# LIVE ENGINE
# =====================================

profit=0
last_trade=-999
loss_streak=0
pause=0

engine=[]
next_signal=None

for i,n in enumerate(live):

    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    if pause>0:

        pause-=1
        state="PAUSE"

    else:

        if next_signal is not None:

            predicted=next_signal

            hit=1 if predicted==g else 0

            profit+=WIN if hit else -LOSS

            state="TRADE"

            last_trade=i

            if hit==0:
                loss_streak+=1
            else:
                loss_streak=0

            if loss_streak>=STOPLOSS:

                pause=PAUSE_ROUNDS
                loss_streak=0

            next_signal=None

        if i-last_trade>GP:

            vote,edge=signal_engine(live[:i],LB,GP)

            if vote:

                next_signal=vote
                state="SIGNAL"

    engine.append({
        "round":i,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state,
        "profit":profit
    })

# =====================================
# METRICS
# =====================================

hits=[x["hit"] for x in engine if x["hit"]!=None]

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
losses=hits.count(0)*LOSS

pf=wins/losses if losses else 0

expect=wr*WIN-(1-wr)*LOSS

profits=[x["profit"] for x in engine]

peak=max(profits) if profits else 0

dd=peak-profits[-1] if profits else 0

# =====================================
# DASHBOARD
# =====================================

c1,c2,c3=st.columns(3)

c1.metric("Live Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(dd,2))
c5.metric("Expectancy",round(expect,3))
c6.metric("Regime",regime(live))

st.caption(f"Config → Lookback {LB} | Gap {GP}")

# =====================================
# LIVE NEXT GROUP
# =====================================

if next_signal:

    st.markdown(
        f"""
        <div style='padding:20px;background:#c62828;color:white;
        border-radius:12px;text-align:center;font-size:30px;font-weight:bold'>
        🔥 NEXT GROUP LIVE SIGNAL 🔥<br>
        GROUP {next_signal}
        </div>
        """,
        unsafe_allow_html=True
    )

else:

    st.info("Scanning for next signal...")

# =====================================
# EQUITY
# =====================================

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame(profits))

# =====================================
# HISTORY
# =====================================

st.subheader("Live History")

hist=pd.DataFrame(engine)

st.dataframe(hist.iloc[::-1],use_container_width=True)
