import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOOKBACK=26
GAP=4

WINDOWS=range(6,19)

WIN=2.5
LOSS=1

WR_THRESHOLD=0.29

TREND_CONFIRM=10
TREND_LOSS=4
TREND_PEAK=50

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


def calc_wr(nums,i,w):

    rec=[]

    for j in range(max(w,i-LOOKBACK),i):

        if j>=w:

            rec.append(group(nums[j])==group(nums[j-w]))

    if len(rec)<12:
        return 0

    return np.mean(rec)


def scan_window(nums,i):

    best=None
    best_score=0

    for w in WINDOWS:

        if i>w:

            wr=calc_wr(nums,i,w)

            ev=wr*WIN-(1-wr)*LOSS

            if wr>WR_THRESHOLD and ev>0:

                score=wr*ev

                if score>best_score:

                    best_score=score
                    best=w

    return best


profit=0
equity=[]
history=[]
hits=[]

locked_window=None
next_signal=None

loss_streak=0

trend_active=False

for i in range(len(numbers)):

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

        state="TRADE"

        next_signal=None

    if locked_window is None:

        w=scan_window(numbers,i)

        if w:

            locked_window=w

    if locked_window and i>locked_window:

        g_pred=group(numbers[i-locked_window])

        if group(numbers[i-1])!=g_pred:

            next_signal=g_pred

    if profit>=TREND_CONFIRM:

        trend_active=True

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


wins=hits.count(True)*WIN
losses=hits.count(False)*LOSS

pf=wins/losses if losses else 0
wr=sum(hits)/len(hits) if hits else 0

equity_np=np.array(equity)

peak=np.maximum.accumulate(equity_np)

drawdown=(peak-equity_np).max()

trades=len(hits)


st.title("🚀 QUANT ENGINE V8")

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
