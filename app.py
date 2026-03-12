import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOOKBACK=26
GAP=4
WINDOWS=range(6,16)

TRAIN_SIZE=200
LOCK_PROFIT=10
LOSS_STREAK_RESET=4

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

# ================= CALC WR =================

def calc_wr(nums,i,window):

    rec=[]

    for j in range(max(window,i-LOOKBACK),i):

        if j>=window:

            rec.append(
                1 if group(nums[j])==group(nums[j-window]) else 0
            )

    if len(rec)<10:
        return 0

    return np.mean(rec)


# ================= SIMULATE =================

def simulate(nums,window):

    profit=0
    next_signal=None
    last_trade=-999

    for i,n in enumerate(nums):

        g=group(n)

        if next_signal is not None:

            hit=(g==next_signal)

            profit+=WIN if hit else -LOSS

            next_signal=None
            last_trade=i

        if i-last_trade>=GAP and i>LOOKBACK:

            wr=calc_wr(nums,i,window)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(nums[i-window])

                if group(nums[i-1])!=g1:

                    next_signal=g1

    return profit


# ================= FIND WINDOW =================

def find_window(train):

    best=None
    best_profit=-999

    for w in WINDOWS:

        p=simulate(train,w)

        if p>=LOCK_PROFIT and p>best_profit:

            best_profit=p
            best=w

    return best


# ================= ENGINE =================

profit=0
equity=[]
hits=[]
history=[]
windows_used=[]

loss_streak=0
window=None
next_signal=None
last_trade=-999

for i in range(TRAIN_SIZE,len(numbers)):

    if window is None:

        train=numbers[i-TRAIN_SIZE:i]

        window=find_window(train)

        loss_streak=0

        if window:
            windows_used.append(window)

    n=numbers[i]
    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    if next_signal is not None:

        predicted=next_signal

        hit=(g==predicted)

        profit+=WIN if hit else -LOSS

        hits.append(hit)

        if hit:
            loss_streak=0
        else:
            loss_streak+=1

        next_signal=None
        last_trade=i

        state="TRADE"

    if window and i-last_trade>=GAP and i>LOOKBACK:

        wr=calc_wr(numbers,i,window)

        ev=wr*WIN-(1-wr)*LOSS

        if ev>0:

            g1=group(numbers[i-window])

            if group(numbers[i-1])!=g1:

                next_signal=g1

                state="SIGNAL"

    if loss_streak>=LOSS_STREAK_RESET:

        window=None

    equity.append(profit)

    history.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit":profit,
        "window":window,
        "state":state

    })


# ================= ANALYTICS =================

wins=hits.count(True)*WIN
losses=hits.count(False)*LOSS

pf=wins/losses if losses else 0

wr=sum(hits)/len(hits) if hits else 0

equity_np=np.array(equity)

peak=np.maximum.accumulate(equity_np)

drawdown=(peak-equity_np).max()

trades=len(hits)


# ================= DASHBOARD =================

st.title("🚀 LIVE BETTING ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(drawdown,2))
c5.metric("Trades",trades)
c6.metric("Window Locked",window)

st.caption(f"Lookback={LOOKBACK} | Gap={GAP}")


# ================= NEXT GROUP =================

st.subheader("Next Group")

if next_signal:

    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:30px;
                font-weight:bold'>
        NEXT GROUP → {next_signal}
    </div>
    """,unsafe_allow_html=True)

else:

    st.info("Scanning...")


# ================= EQUITY =================

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"profit":equity}))


# ================= HISTORY =================

st.subheader("History")

hist_df=pd.DataFrame(history)

st.dataframe(hist_df.iloc[::-1],use_container_width=True)
