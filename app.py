import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOWS=range(8,13)
LOOKBACKS=range(18,33)
GAPS=[3,4,5]

TRAIN_SIZE=400
STEP=400

WIN=2.5
LOSS=1

st.set_page_config(layout="wide")

# ================= GROUP =================

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ================= LOAD DATA =================

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()


# ================= EDGE FUNCTION =================

def calc_wr(nums,i,W,LB):

    rec=[]

    for j in range(max(W,i-LB),i):

        if j>=W:

            rec.append(
                1 if group(nums[j])==group(nums[j-W]) else 0
            )

    if len(rec)<10:
        return 0

    return np.mean(rec)


# ================= BACKTEST CONFIG =================

def simulate(nums,W,LB,GAP):

    profit=0
    next_signal=None
    last_trade=-999

    for i,n in enumerate(nums):

        g=group(n)

        if next_signal is not None:

            hit=1 if g==next_signal else 0

            profit+=WIN if hit else -LOSS

            next_signal=None
            last_trade=i

        if i-last_trade>=GAP and i>LB:

            wr=calc_wr(nums,i,W,LB)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(nums[i-W])

                if group(nums[i-1])!=g1:

                    next_signal=g1

    return profit


# ================= FIND BEST CONFIG =================

def find_best(train):

    best_profit=-999
    best_cfg=(9,26,4)

    for W in WINDOWS:
        for LB in LOOKBACKS:
            for G in GAPS:

                p=simulate(train,W,LB,G)

                if p>best_profit:

                    best_profit=p
                    best_cfg=(W,LB,G)

    return best_cfg


# ================= WALK FORWARD ENGINE =================

profit=0
equity=[]
history=[]
hits=[]

next_signal=None
last_trade=-999

current_cfg=(9,26,4)

for start in range(TRAIN_SIZE,len(numbers),STEP):

    train=numbers[:start]

    current_cfg=find_best(train)

    W,LB,GAP=current_cfg

    end=min(start+STEP,len(numbers))

    segment=numbers[start:end]

    for j,n in enumerate(segment):

        i=start+j

        g=group(n)

        predicted=None
        hit=None
        state="SCAN"

        if next_signal is not None:

            predicted=next_signal

            hit=1 if g==predicted else 0

            profit+=WIN if hit else -LOSS

            hits.append(hit)

            next_signal=None
            last_trade=i

            state="TRADE"

        if i-last_trade>=GAP and i>LB:

            wr=calc_wr(numbers,i,W,LB)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(numbers[i-W])

                if group(numbers[i-1])!=g1:

                    next_signal=g1
                    state="SIGNAL"

        equity.append(profit)

        history.append({

            "round":i+1,
            "number":n,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":profit,
            "window":W,
            "lookback":LB,
            "gap":GAP

        })


# ================= METRICS =================

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0

peak=max(equity) if equity else 0
dd=peak-equity[-1] if equity else 0


# ================= DASHBOARD =================

st.title("🚀 WALK FORWARD LIVE ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5=st.columns(2)

c4.metric("Drawdown",round(dd,2))
c5.metric("Trades",len(hits))

st.subheader("Current Config")

st.write(current_cfg)

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Next Group")

if next_signal:

    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
    border-radius:10px;text-align:center;font-size:30px'>
    NEXT GROUP → {next_signal}
    </div>
    """,unsafe_allow_html=True)

else:

    st.info("Scanning...")

st.subheader("History")

st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
