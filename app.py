import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_STEP=400

WIN=2.5
LOSS=1

WINDOWS=range(6,13)
LOOKBACKS=range(18,41)
GAPS=range(2,7)

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

def simulate(nums,LB,G,W):

    profit=0
    hits=[]
    next_signal=None
    last_trade=-999

    for i,n in enumerate(nums):

        g=group(n)

        if next_signal is not None:

            hit=1 if next_signal==g else 0
            hits.append(hit)

            profit+=WIN if hit else -LOSS

            next_signal=None
            last_trade=i

        if i-last_trade>G and i>LB:

            rec=[]

            for j in range(max(W,i-LB),i):

                if j>=W:

                    rec.append(
                        1 if group(nums[j])==group(nums[j-W]) else 0
                    )

            if len(rec)>10:

                wr=np.mean(rec)
                ev=wr*WIN-(1-wr)*LOSS

                if ev>0:

                    g1=group(nums[i-W])

                    if group(nums[i-1])!=g1:

                        next_signal=g1

    return profit,hits

# =========================
# WALK FORWARD
# =========================

profit=0
equity=[]
segments=[]

start=0

while start+TRAIN_STEP<len(numbers):

    train=numbers[:start+TRAIN_STEP]

    best=-999
    best_cfg=(26,4,9)

    for LB in LOOKBACKS:
        for GP in GAPS:
            for W in WINDOWS:

                p,_=simulate(train,LB,GP,W)

                if p>best:

                    best=p
                    best_cfg=(LB,GP,W)

    LB,GP,W=best_cfg

    trade=numbers[start+TRAIN_STEP:start+TRAIN_STEP*2]

    p,hits=simulate(trade,LB,GP,W)

    profit+=p

    equity.append(profit)

    segments.append({
        "start":start,
        "LB":LB,
        "GAP":GP,
        "WINDOW":W,
        "profit":p
    })

    start+=TRAIN_STEP

# =========================
# DASHBOARD
# =========================

st.title("LIVE WALK FORWARD ENGINE")

st.metric("Total Profit",round(profit,2))

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Segments")

st.dataframe(pd.DataFrame(segments))
