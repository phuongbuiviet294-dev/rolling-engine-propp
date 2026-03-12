import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=800
TRADE_SIZE=400

WINDOWS=[9,10,11]
LOOKBACKS=range(22,29)
GAP=4

WIN=2.5
LOSS=1

CONF_THRESHOLD=0.31

st.set_page_config(layout="wide")

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()

# ---------------- SIMULATION ----------------

def simulate(nums,LB,W):

    profit=0
    next_signal=None
    last_trade=-999

    for i,n in enumerate(nums):

        g=group(n)

        if next_signal is not None:

            hit=1 if next_signal==g else 0

            profit+=WIN if hit else -LOSS

            next_signal=None
            last_trade=i

        if i-last_trade>GAP and i>LB:

            rec=[]

            for j in range(max(W,i-LB),i):

                if j>=W:

                    rec.append(
                        1 if group(nums[j])==group(nums[j-W]) else 0
                    )

            if len(rec)>20:

                wr=np.mean(rec)

                ev=wr*WIN-(1-wr)*LOSS

                if ev>0 and wr>CONF_THRESHOLD:

                    g1=group(nums[i-W])

                    if group(nums[i-1])!=g1:

                        next_signal=g1

    return profit


# ---------------- FIND CONFIG ----------------

def find_best(train):

    best_profit=-999
    best=(26,9)

    for LB in LOOKBACKS:
        for W in WINDOWS:

            p=simulate(train,LB,W)

            if p>best_profit:

                best_profit=p
                best=(LB,W)

    return best


# ---------------- WALK FORWARD ----------------

profit=0
equity=[]
history=[]
hits=[]

next_signal=None
last_trade=-999

for start in range(TRAIN_SIZE,len(numbers),TRADE_SIZE):

    train=numbers[:start]

    LB,W=find_best(train)

    end=min(start+TRADE_SIZE,len(numbers))

    segment=numbers[start:end]

    for j,n in enumerate(segment):

        idx=start+j

        g=group(n)

        predicted=None
        hit=None
        state="SCAN"

        # ---------- EXECUTE ----------

        if next_signal is not None:

            predicted=next_signal

            hit=1 if predicted==g else 0

            profit+=WIN if hit else -LOSS

            hits.append(hit)

            next_signal=None
            last_trade=idx

            state="TRADE"

        # ---------- SIGNAL ----------

        if idx-last_trade>GAP and idx>LB:

            votes=[]

            for W in WINDOWS:

                rec=[]

                for k in range(max(W,idx-LB),idx):

                    if k>=W:

                        rec.append(
                            1 if group(numbers[k])==group(numbers[k-W]) else 0
                        )

                if len(rec)>20:

                    wr=np.mean(rec)

                    ev=wr*WIN-(1-wr)*LOSS

                    if ev>0 and wr>CONF_THRESHOLD:

                        g1=group(numbers[idx-W])

                        if group(numbers[idx-1])!=g1:

                            votes.append(g1)

            if len(votes)>=2:

                next_signal=max(set(votes), key=votes.count)
                state="SIGNAL"

        equity.append(profit)

        history.append({

            "round":idx+1,
            "number":n,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":profit

        })


# ---------------- METRICS ----------------

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0

peak=max(equity)
dd=peak-equity[-1]

# ---------------- DASHBOARD ----------------

st.title("🚀 QUANT ENGINE V2")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

st.metric("Drawdown",round(dd,2))

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
