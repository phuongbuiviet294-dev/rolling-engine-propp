import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOOKBACK=26
GAP=4

WINDOWS=[6,8,10,12,15,18]

WIN=2.5
LOSS=1

WR_THRESHOLD=0.29

RESET_LOSS=4

st.set_page_config(layout="wide")

# ---------------- GROUP ----------------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------------- LOAD ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()

# ---------------- WR ----------------

def calc_wr(nums,i,w):

    rec=[]

    for j in range(max(w,i-LOOKBACK),i):

        if j>=w:

            rec.append(
                group(nums[j])==group(nums[j-w])
            )

    if len(rec)<12:
        return 0

    return np.mean(rec)

# ---------------- SIGNAL ----------------

def window_signal(nums,i,w):

    wr=calc_wr(nums,i,w)

    if wr<WR_THRESHOLD:
        return None

    ev=wr*WIN-(1-wr)*LOSS

    if ev<=0:
        return None

    g=group(nums[i-w])

    if group(nums[i-1])!=g:

        return g

    return None

# ---------------- VOTING ----------------

def voting_signal(nums,i):

    votes=[]

    for w in WINDOWS:

        if i>w:

            sig=window_signal(nums,i,w)

            if sig:

                votes.append(sig)

    if len(votes)<3:
        return None,len(votes)

    g=max(set(votes),key=votes.count)

    if votes.count(g)>=3:

        return g,len(votes)

    return None,len(votes)

# ---------------- ENGINE ----------------

profit=0
equity=[]
history=[]
hits=[]

loss_streak=0
next_signal=None
last_trade=-999
strength=0

for i in range(len(numbers)):

    n=numbers[i]
    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    # TRADE

    if next_signal is not None:

        predicted=next_signal

        hit=(g==predicted)

        profit+=WIN if hit else -LOSS

        hits.append(hit)

        if hit:
            loss_streak=0
        else:
            loss_streak+=1

        state="TRADE"

        next_signal=None
        last_trade=i

    # SIGNAL

    if i-last_trade>=GAP and i>LOOKBACK:

        sig,strength=voting_signal(numbers,i)

        if sig:

            next_signal=sig

            state="SIGNAL"

    # RESET

    if loss_streak>=RESET_LOSS:

        next_signal=None
        last_trade=-999
        loss_streak=0

    equity.append(profit)

    history.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit":profit,
        "votes":strength,
        "state":state

    })


# ---------------- ANALYTICS ----------------

wins=hits.count(True)*WIN
losses=hits.count(False)*LOSS

pf=wins/losses if losses else 0

wr=sum(hits)/len(hits) if hits else 0

equity_np=np.array(equity)

peak=np.maximum.accumulate(equity_np)

drawdown=(peak-equity_np).max()

trades=len(hits)

# ---------------- DASHBOARD ----------------

st.title("🚀 QUANT ENGINE V6")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(drawdown,2))
c5.metric("Trades",trades)
c6.metric("Signal Strength",strength)

# NEXT GROUP

st.subheader("Next Group")

if next_signal:

    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
    border-radius:12px;text-align:center;font-size:32px'>
    NEXT GROUP → {next_signal}
    </div>
    """,unsafe_allow_html=True)

else:

    st.info("Scanning...")

# EQUITY

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"profit":equity}))

# HISTORY

st.subheader("History")

st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
