import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW=9
LOOKBACK=26
GAP=4

WIN=2.5
LOSS=1

TRAIN_STEP=400

st.set_page_config(layout="wide")

# ================= GROUP =================

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ================= LOAD =================

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()

# ================= EDGE =================

def edge(nums,i):

    rec=[]

    for j in range(max(WINDOW,i-LOOKBACK),i):

        if j>=WINDOW:

            rec.append(
                1 if group(nums[j])==group(nums[j-WINDOW]) else 0
            )

    if len(rec)<10:
        return 0

    return np.mean(rec)


# ================= ENGINE =================

profit=0
equity=[]
history=[]
hits=[]

next_signal=None
last_trade=-999

for i,n in enumerate(numbers):

    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted=next_signal

        hit=1 if predicted==g else 0

        profit+=WIN if hit else -LOSS

        hits.append(hit)

        last_trade=i
        next_signal=None

        state="TRADE"

    # ===== FIND SIGNAL =====

    if i-last_trade>=GAP and i>LOOKBACK:

        wr=edge(numbers,i)

        ev=wr*WIN-(1-wr)*LOSS

        if ev>0:

            g1=group(numbers[i-WINDOW])

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
        "profit":profit

    })


# ================= METRICS =================

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0

peak=max(equity) if equity else 0
dd=peak-equity[-1] if equity else 0

# ================= DASHBOARD =================

st.title("🚀 LIVE TRADING ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5=st.columns(2)

c4.metric("Drawdown",round(dd,2))
c5.metric("Trades",len(hits))

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
