import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOWS=range(6,19)

LOOKBACK=26
GAP=4

WIN=2.5
LOSS=1

TREND_START=10
TREND_LOSS=4
TREND_RESET=60

st.set_page_config(layout="wide")

def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

@st.cache_data(ttl=5)
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers=load()

# ---------- simulate ----------

def simulate_segment(nums,w,start,end):

    profit=0
    last=-999

    for i in range(start,end):

        if i>w and i-last>=GAP:

            pred=group(nums[i-w])

            if group(nums[i-1])!=pred:

                if group(nums[i])==pred:
                    profit+=WIN
                else:
                    profit-=LOSS

                last=i

    return profit


# ---------- window selection ----------

segments=4
seg_size=len(numbers)//segments

best_window=None
best_score=-999

for w in WINDOWS:

    profits=[]

    for s in range(segments):

        start=s*seg_size
        end=start+seg_size

        p=simulate_segment(numbers,w,start,end)

        profits.append(p)

    avg_profit=np.mean(profits)
    stability=sum([1 for p in profits if p>0])

    score=avg_profit+stability*20

    if score>best_score:

        best_score=score
        best_window=w

if best_window is None:
    best_window=9

locked_window=best_window


# ---------- live engine ----------

profit=0
equity=[]
hits=[]
history=[]

loss_streak=0
last_trade=-999

next_signal=None
signal_strength=0

for i in range(len(numbers)):

    n=numbers[i]
    g=group(n)

    predicted=None
    hit=None

    if next_signal and i-last_trade>=GAP:

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
        signal_strength=0


    if locked_window is not None and i>locked_window:

        pred=group(numbers[i-locked_window])

        if group(numbers[i-1])!=pred:

            signal_strength+=1

            if signal_strength>=2:
                next_signal=pred


    if loss_streak>=TREND_LOSS or profit>=TREND_RESET:

        locked_window=best_window
        loss_streak=0


    equity.append(profit)

    history.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit":profit
    })


# ---------- analytics ----------

wins=hits.count(True)*WIN
losses=hits.count(False)*LOSS

pf=wins/losses if losses else 0
wr=sum(hits)/len(hits) if hits else 0

eq=np.array(equity)
peak=np.maximum.accumulate(eq)
drawdown=(peak-eq).max()

st.title("🚀 QUANT ENGINE V12")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5,c6=st.columns(3)

c4.metric("Drawdown",round(drawdown,2))
c5.metric("Trades",len(hits))
c6.metric("Window Locked",locked_window)

st.subheader("Equity Curve")
st.line_chart(pd.DataFrame({"profit":equity}))

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

st.subheader("History")
st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
