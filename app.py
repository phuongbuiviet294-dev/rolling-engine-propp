import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOOKBACK=26
GAP=4

WINDOWS=range(6,19)

TRAIN_SMALL=400
TRAIN_LARGE=1000

WIN=2.5
LOSS=1

WR_THRESHOLD=0.29
LOCK_PROFIT=10

RESET_LOSS_STREAK=4

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

def calc_wr(nums,i,window):

    rec=[]

    for j in range(max(window,i-LOOKBACK),i):

        if j>=window:

            rec.append(
                group(nums[j])==group(nums[j-window])
            )

    if len(rec)<12:
        return 0

    return np.mean(rec)


# ---------------- SIGNAL ----------------

def get_signal(nums,i,window):

    wr=calc_wr(nums,i,window)

    if wr<WR_THRESHOLD:
        return None

    ev=wr*WIN-(1-wr)*LOSS

    if ev<=0:
        return None

    g=group(nums[i-window])

    if group(nums[i-1])!=g:

        return g

    return None


# ---------------- WINDOW SEARCH ----------------

def find_window(train):

    best=None
    best_profit=-999

    for w in WINDOWS:

        profit=0
        next_signal=None
        last_trade=-999

        for i in range(len(train)):

            g=group(train[i])

            if next_signal is not None:

                hit=(g==next_signal)

                profit+=WIN if hit else -LOSS

                next_signal=None
                last_trade=i

            if i-last_trade>=GAP and i>LOOKBACK:

                sig=get_signal(train,i,w)

                if sig:

                    next_signal=sig

        if profit>best_profit:

            best_profit=profit
            best=w

    return best,best_profit


# ---------------- ENGINE ----------------

profit=0
equity=[]
history=[]
hits=[]

window=None
next_signal=None

last_trade=-999
loss_streak=0

train_size=TRAIN_SMALL

for i in range(len(numbers)):

    # -------- TRAIN --------

    if window is None and i>train_size:

        train=numbers[i-train_size:i]

        w,p=find_window(train)

        if p<LOCK_PROFIT and train_size==TRAIN_SMALL:

            train_size=TRAIN_LARGE
            continue

        window=w

        loss_streak=0


    n=numbers[i]
    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    # -------- TRADE --------

    if next_signal is not None and window is not None:

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


    # -------- SIGNAL --------

    if window is not None and i-last_trade>=GAP and i>LOOKBACK:

        sig=get_signal(numbers,i,window)

        if sig:

            next_signal=sig

            state="SIGNAL"


    # -------- RESET --------

    if loss_streak>=RESET_LOSS_STREAK:

        window=None
        next_signal=None
        last_trade=-999
        train_size=TRAIN_SMALL
        loss_streak=0


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

st.title("🚀 QUANT BETTING ENGINE V5")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(drawdown,2))
c5.metric("Trades",trades)
c6.metric("Window Locked",window)

st.caption(f"Lookback={LOOKBACK} | Gap={GAP}")


# ---------------- NEXT GROUP ----------------

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


# ---------------- EQUITY ----------------

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"profit":equity}))


# ---------------- HISTORY ----------------

st.subheader("History")

st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
