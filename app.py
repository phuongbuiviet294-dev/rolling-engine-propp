import streamlit as st
import pandas as pd
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=200
LOCK=200

# ---------- group ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------- load ----------
@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    return df["number"].dropna().astype(int).tolist()


numbers=load()
groups=[group(n) for n in numbers]


# ---------- predictor ----------
def predict(g,window):

    if len(g)<window:
        return None

    c=Counter(g[-window:])
    return max(c,key=c.get)


# ---------- evaluate window ----------
def evaluate_window(data,window):

    profit=0
    peak=0
    dd=0
    trades=0

    for i in range(window,len(data)-1):

        pred=predict(data[:i],window)
        actual=data[i]

        if pred is None:
            continue

        trades+=1

        if pred==actual:
            profit+=2.5
        else:
            profit-=1

        peak=max(peak,profit)
        dd=max(dd,peak-profit)

    score=profit-0.5*dd

    return profit,trades,dd,score


# ---------- find best window ----------
def find_best_window(data):

    results=[]

    for w in range(8,18):

        p,t,d,s=evaluate_window(data,w)

        results.append((w,p,t,d,s))

    df=pd.DataFrame(results,
        columns=["window","profit","trades","drawdown","score"])

    best=df.sort_values("score",ascending=False).iloc[0]

    return int(best.window),df


# ---------- backtest ----------
profit=0
peak=0
dd=0

trades=0
wins=0

history=[]

hits=[]

best_window,scan_table=find_best_window(groups[:SCAN])

lock_counter=0


for i in range(SCAN,len(groups)-1):

    if lock_counter>=LOCK:

        best_window,_=find_best_window(groups[i-SCAN:i])

        lock_counter=0


    pred=predict(groups[:i],best_window)
    actual=groups[i]


    allow_trade=False

    if len(hits)>=2:

        if hits[-1]==1 and hits[-2]==1:

            allow_trade=True


    hit=0

    if allow_trade:

        trades+=1

        if pred==actual:

            profit+=2.5
            hit=1
            wins+=1

        else:

            profit-=1


    hits.append(hit)

    peak=max(peak,profit)
    dd=max(dd,peak-profit)

    history.append(profit)

    lock_counter+=1


wr = wins/trades if trades else 0


# ---------- UI ----------
st.title("⚡ V55 Regime Detection Engine")


c1,c2,c3=st.columns(3)

c1.metric("Best Window",best_window)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))


c4,c5=st.columns(2)

c4.metric("Profit",profit)
c5.metric("Drawdown",dd)


# ---------- next group ----------
next_pred=predict(groups,best_window)

st.subheader("Next Group")

st.success(f"PREDICT GROUP {next_pred}")


# ---------- equity ----------
st.subheader("Equity Curve")

st.line_chart(history)


# ---------- window scan ----------
st.subheader("Window Scan Result")

st.dataframe(scan_table)
