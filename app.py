import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOWS=range(8,13)
LOOKBACKS=range(18,33)
GAPS=[3,4,5]

TRAIN_SIZE=1000

WIN=2.5
LOSS=1

TARGET_PROFIT=50
MAX_DRAWDOWN=20
LOSS_STREAK_LIMIT=5

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


# ================= EDGE =================

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


# ================= SIMULATION =================

def simulate(nums,W,LB,GAP):

    profit=0
    trades=0
    hits=[]

    next_signal=None
    last_trade=-999

    for i,n in enumerate(nums):

        g=group(n)

        if next_signal is not None:

            hit=1 if g==next_signal else 0

            profit+=WIN if hit else -LOSS
            trades+=1
            hits.append(hit)

            next_signal=None
            last_trade=i

        if i-last_trade>=GAP and i>LB:

            wr=calc_wr(nums,i,W,LB)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(nums[i-W])

                if group(nums[i-1])!=g1:

                    next_signal=g1

    wins=hits.count(1)*WIN
    losses=hits.count(0)*LOSS

    pf=wins/losses if losses>0 else 0

    return profit,pf,trades


# ================= FIND BEST CONFIG =================

def find_config(train):

    best=None
    best_pf=0

    for W in WINDOWS:
        for LB in LOOKBACKS:
            for G in GAPS:

                profit,pf,trades=simulate(train,W,LB,G)

                if profit>=15 and pf>best_pf and trades>=20:

                    best_pf=pf
                    best=(W,LB,G)

    return best


# ================= ENGINE =================

profit=0
equity=[]
history=[]

cycle_profit=0
peak_cycle=0
loss_streak=0

config=None
next_signal=None
last_trade=-999

for i,n in enumerate(numbers):

    # ===== TRAIN =====

    if config is None and i>=TRAIN_SIZE:

        train=numbers[i-TRAIN_SIZE:i]

        config=find_config(train)

        cycle_profit=0
        peak_cycle=0
        loss_streak=0


    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    if next_signal is not None:

        predicted=next_signal

        hit=1 if g==predicted else 0

        p=WIN if hit else -LOSS

        profit+=p
        cycle_profit+=p

        if hit==0:
            loss_streak+=1
        else:
            loss_streak=0

        peak_cycle=max(peak_cycle,cycle_profit)

        next_signal=None
        last_trade=i

        state="TRADE"

    if config:

        W,LB,GAP=config

        if i-last_trade>=GAP and i>LB:

            wr=calc_wr(numbers,i,W,LB)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(numbers[i-W])

                if group(numbers[i-1])!=g1:

                    next_signal=g1
                    state="SIGNAL"


    # ===== RESET RULES =====

    if config:

        if cycle_profit>=TARGET_PROFIT:

            config=None

        if peak_cycle-cycle_profit>=MAX_DRAWDOWN:

            config=None

        if loss_streak>=LOSS_STREAK_LIMIT:

            config=None


    equity.append(profit)

    history.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit":profit,
        "state":state,
        "config":config

    })


# ================= DASHBOARD =================

st.title("🚀 ADAPTIVE QUANT ENGINE")

st.metric("Total Profit",round(profit,2))

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Current Config")

st.write(config)

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
