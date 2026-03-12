import streamlit as st
import pandas as pd
import numpy as np

# ==============================
# CONFIG
# ==============================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1

TRAIN_STEP=400
TRADE_STEP=400

WINDOWS=[5,7,9,11,13,15]

LOOKBACK_RANGE=range(20,35)
GAP_RANGE=range(2,6)

EDGE_THRESHOLD=0.05

AUTO_REFRESH=10

st.set_page_config(layout="wide")
st.title("🚀 QUANT LIVE TRADING ENGINE")

# ==============================
# GROUP
# ==============================

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ==============================
# LOAD DATA
# ==============================

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int).tolist()

    return numbers

numbers=load()

# ==============================
# REGIME DETECTION
# ==============================

def detect_regime(data):

    if len(data)<80:
        return "UNKNOWN"

    groups=[group(x) for x in data[-80:]]

    transitions=0

    for i in range(1,len(groups)):

        if groups[i]!=groups[i-1]:
            transitions+=1

    rate=transitions/len(groups)

    if rate>0.75:
        return "RANDOM"

    if rate<0.55:
        return "TREND"

    return "MIXED"

# ==============================
# PATTERN ENGINE
# ==============================

def pattern_vote(data,lookback):

    votes=[]
    edges=[]

    for W in WINDOWS:

        if len(data)<lookback:
            continue

        seq=[]

        start=max(W,len(data)-lookback)

        for j in range(start,len(data)):

            if j>=W:

                seq.append(
                    1 if group(data[j])==group(data[j-W]) else 0
                )

        if len(seq)<15:
            continue

        wr=np.mean(seq)

        ev=wr*WIN-(1-wr)*LOSS

        if ev>EDGE_THRESHOLD:

            g1=group(data[-W])

            if group(data[-1])!=g1:

                votes.append(g1)
                edges.append(ev)

    if len(votes)==0:
        return None,0

    vote=pd.Series(votes).mode()[0]

    confidence=len(votes)/len(WINDOWS)

    edge=np.mean(edges)

    return vote,confidence*edge

# ==============================
# OPTIMIZER
# ==============================

def optimize(train):

    best=-999
    best_cfg=(26,3)

    for LB in LOOKBACK_RANGE:

        for GP in GAP_RANGE:

            profit=0
            last=-999

            for i in range(len(train)):

                if i-last<GP:
                    continue

                vote,edge=pattern_vote(train[:i],LB)

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

# ==============================
# WALK FORWARD ENGINE
# ==============================

profit=0
engine=[]
windows=[]

train_end=TRAIN_STEP

while train_end+TRADE_STEP<=len(numbers):

    train=numbers[:train_end]

    LB,GP=optimize(train)

    trade=numbers[train_end:train_end+TRADE_STEP]

    last_trade=-999
    next_signal=None

    window_profit=0

    for i,n in enumerate(trade):

        g=group(n)

        predicted=None
        hit=None
        state="SCAN"

        if next_signal is not None:

            predicted=next_signal

            hit=1 if predicted==g else 0

            profit+=WIN if hit else -LOSS
            window_profit+=WIN if hit else -LOSS

            state="TRADE"

            last_trade=i
            next_signal=None

        if i-last_trade>GP:

            vote,edge=pattern_vote(trade[:i],LB)

            regime=detect_regime(trade[:i])

            if vote and regime!="RANDOM":

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

    windows.append({

        "train_range":f"1-{train_end}",
        "trade_range":f"{train_end+1}-{train_end+TRADE_STEP}",
        "lookback":LB,
        "gap":GP,
        "profit":window_profit

    })

    train_end+=TRADE_STEP

# ==============================
# NEXT GROUP LIVE
# ==============================

LB,GP=optimize(numbers)

vote,edge=pattern_vote(numbers,LB)

regime=detect_regime(numbers)

# ==============================
# METRICS
# ==============================

hits=[x["hit"] for x in engine if x["hit"]!=None]

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
losses=hits.count(0)*LOSS

pf=wins/losses if losses else 0

profits=[x["profit"] for x in engine]

peak=max(profits) if profits else 0
dd=peak-profits[-1] if profits else 0

expect=wr*WIN-(1-wr)*LOSS

# ==============================
# DASHBOARD
# ==============================

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(dd,2))
c5.metric("Expectancy",round(expect,3))
c6.metric("Regime",regime)

# ==============================
# NEXT SIGNAL
# ==============================

if vote and regime!="RANDOM":

    st.markdown(

        f"""
        <div style='padding:25px;background:#c62828;color:white;
        border-radius:12px;text-align:center;font-size:30px;font-weight:bold'>

        NEXT GROUP: {vote}<br>
        EDGE: {round(edge,3)}

        </div>
        """,

        unsafe_allow_html=True

    )

else:

    st.info("Scanning market...")

# ==============================
# EQUITY
# ==============================

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame(profits))

# ==============================
# HISTORY
# ==============================

st.subheader("Live History")

hist=pd.DataFrame(engine)

st.dataframe(hist.iloc[::-1],use_container_width=True)

# ==============================
# WINDOW REPORT
# ==============================

st.subheader("Walk Forward Windows")

st.dataframe(pd.DataFrame(windows))
