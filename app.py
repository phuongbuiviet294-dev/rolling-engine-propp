import streamlit as st
import pandas as pd
from collections import Counter

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW_RANGE=range(8,18)

SCAN_ROUNDS=200
LOOKBACK_STABILITY=26
LOOKBACK_REGIME=50

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

groups=[group(n) for n in numbers]

# ================= PREDICT =================

def predict_freq(data,window):

    if len(data)<window:
        return None,0

    c=Counter(data[-window:])

    pred=max(c,key=c.get)

    conf=c[pred]/window

    return pred,conf

# ================= WINDOW EVALUATION =================

def eval_window(data,window):

    profit=0
    equity=[]
    peak=0
    dd=0

    for i in range(window,len(data)-1):

        pred,_=predict_freq(data[:i],window)

        actual=data[i]

        if pred==actual:

            profit+=WIN

        else:

            profit-=LOSS

        equity.append(profit)

        peak=max(peak,profit)

        dd=max(dd,peak-profit)

    score=profit-dd

    return profit,dd,score

# ================= WINDOW SCAN =================

def scan_windows(data):

    rows=[]

    for w in WINDOW_RANGE:

        p,dd,s=eval_window(data,w)

        rows.append([w,p,dd,s])

    df=pd.DataFrame(rows,columns=["window","profit","drawdown","score"])

    best=df.sort_values("score",ascending=False).iloc[0]

    return int(best.window),df

# ================= INITIAL SCAN =================

best_window,window_table=scan_windows(groups[:SCAN_ROUNDS])

window_locked=True

# ================= ENGINE =================

profit=0
hits=[]
history=[]
equity=[]

trades=0
wins=0

current_window=best_window

for i in range(SCAN_ROUNDS,len(groups)-1):

    pred,_=predict_freq(groups[:i],current_window)

    actual=groups[i]

    predicted=None
    hit=None
    state="SCAN"

    if pred is not None:

        predicted=pred

        hit=1 if pred==actual else 0

        hits.append(hit)

    # ===== STABILITY =====

    stability=False

    if len(hits)>=LOOKBACK_STABILITY:

        hr26=sum(hits[-LOOKBACK_STABILITY:])/LOOKBACK_STABILITY

        if hr26>=0.5:
            stability=True

    # ===== MOMENTUM =====

    momentum=False

    if len(hits)>=2:

        if hits[-1]==1 and hits[-2]==1:
            momentum=True

    # ===== TRADE =====

    if momentum and stability:

        trades+=1

        if predicted==actual:

            profit+=WIN
            wins+=1

        else:

            profit-=LOSS

        state="TRADE"

    equity.append(profit)

    history.append({

        "round":i,
        "actual":actual,
        "predicted":predicted,
        "hit":hit,
        "profit":profit,
        "state":state,
        "window":current_window

    })

    # ===== REGIME SHIFT =====

    if len(hits)>=LOOKBACK_REGIME:

        hr50=sum(hits[-LOOKBACK_REGIME:])/LOOKBACK_REGIME

        if hr50<0.35:

            # unlock + rescan
            new_window,_=scan_windows(groups[i-200:i])

            current_window=new_window

# ================= METRICS =================

wr=wins/trades if trades else 0

peak=max(equity) if equity else 0
dd=max(peak-x for x in equity) if equity else 0

hist_df=pd.DataFrame(history)

# ================= NEXT SIGNAL =================

next_pred,_=predict_freq(groups,current_window)

signal=False

if len(hits)>=LOOKBACK_STABILITY:

    hr26=sum(hits[-LOOKBACK_STABILITY:])/LOOKBACK_STABILITY

    if hr26>=0.5:

        if len(hits)>=2 and hits[-1]==1 and hits[-2]==1:

            signal=True

# ================= UI =================

st.title("⚡ V64 Adaptive Regime Engine")

col1,col2,col3=st.columns(3)

col1.metric("Current Window",current_window)
col2.metric("Trades",trades)
col3.metric("Winrate %",round(wr*100,2))

col4,col5=st.columns(2)

col4.metric("Profit",round(profit,2))
col5.metric("Drawdown",round(dd,2))

# ================= NEXT GROUP =================

st.subheader("Next Group")

if signal:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info("SKIP")

# ================= EQUITY =================

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

# ================= WINDOW TABLE =================

st.subheader("Initial Window Scan")

st.dataframe(window_table)

# ================= HISTORY =================

st.subheader("Trade History")

st.dataframe(hist_df.tail(50),use_container_width=True)
