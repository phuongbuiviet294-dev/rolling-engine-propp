import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOOKBACK=26
GAP=4

WINDOWS=range(6,19)

TRAIN_SIZE=400

WIN=2.5
LOSS=1

WR_THRESHOLD=0.29

TREND_CONFIRM=10
TREND_LOSS=4
TREND_PEAK=50

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

def calc_wr(nums,start,end,w):

    rec=[]

    for j in range(start,end):

        if j>=w:

            rec.append(group(nums[j])==group(nums[j-w]))

    if len(rec)<20:
        return 0

    return np.mean(rec)


# ---------------- WINDOW TRAIN ----------------

def train_window(nums,start,end):

    best=None
    best_score=0

    for w in WINDOWS:

        wr=calc_wr(nums,start,end,w)

        ev=wr*WIN-(1-wr)*LOSS

        if wr>WR_THRESHOLD and ev>0:

            score=wr*ev

            if score>best_score:

                best_score=score
                best=w

    return best


# ---------------- ENGINE ----------------

profit=0
equity=[]
history=[]
hits=[]

locked_window=None
next_signal=None

last_trade=-999

loss_streak=0
trend_active=False

train_start=0
train_end=TRAIN_SIZE

for i in range(len(numbers)):

    n=numbers[i]
    g=group(n)

    predicted=None
    hit=None
    state="SCAN"

    # ---------------- TRAIN ----------------

    if locked_window is None and i>=train_end:

        locked_window=train_window(numbers,train_start,train_end)

        train_start=i
        train_end=i+TRAIN_SIZE


    # ---------------- TRADE ----------------

    if next_signal is not None and i-last_trade>=GAP:

        predicted=next_signal

        hit=(g==predicted)

        profit+=WIN if hit else -LOSS

        hits.append(hit)

        last_trade=i

        if hit:
            loss_streak=0
        else:
            loss_streak+=1

        next_signal=None
        state="TRADE"


    # ---------------- SIGNAL ----------------

    if locked_window and i-last_trade>=GAP:

        if i>locked_window:

            g_pred=group(numbers[i-locked_window])

            if group(numbers[i-1])!=g_pred:

                next_signal=g_pred
                state="SIGNAL"


    # ---------------- TREND ----------------

    if profit>=TREND_CONFIRM:

        trend_active=True


    # ---------------- RESET ----------------

    if trend_active and loss_streak>=TREND_LOSS:

        locked_window=None
        trend_active=False
        loss_streak=0


    if profit>=TREND_PEAK:

        locked_window=None
        trend_active=False
        loss_streak=0


    equity.append(profit)

    history.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit":profit,
        "window":locked_window,
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

st.title("🚀 QUANT ENGINE V9 PRO")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(drawdown,2))
c5.metric("Trades",trades)
c6.metric("Window Locked",locked_window)


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


st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"profit":equity}))


st.subheader("History")

st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
