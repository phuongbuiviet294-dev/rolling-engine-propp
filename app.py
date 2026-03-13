import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# ---------- group mapping ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ---------- load data ----------
@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

ROUNDS=len(groups)

# ---------- prediction ----------
def predict(g,window):

    if len(g)<window:
        return None

    w=g[-window:]

    c=Counter(w)

    return max(c,key=c.get)

# ---------- backtest ----------
results=[]

for window in range(8,18):

    profit=0
    peak=0
    dd=0

    trades=0
    wins=0

    hits=[]
    history=[]

    for i in range(window,ROUNDS-1):

        pred=predict(groups[:i],window)

        if pred is None:
            continue

        actual=groups[i]

        hit=1 if pred==actual else 0

        hits.append(hit)

        trade=False

        if len(hits)>=2 and hits[-2:]==[1,1]:

            trade=True

        if trade:

            trades+=1

            if hit:

                profit+=2.5
                wins+=1

            else:

                profit-=1

        peak=max(peak,profit)

        dd=max(dd,peak-profit)

        history.append({

            "round":i,
            "pred":pred,
            "actual":actual,
            "hit":hit,
            "trade":trade,
            "profit":profit
        })

    wr=wins/trades if trades else 0

    results.append({

        "window":window,
        "profit":profit,
        "trades":trades,
        "winrate":wr,
        "drawdown":dd,
        "history":history
    })

perf=pd.DataFrame(results).drop(columns=["history"])

best=perf.sort_values("profit",ascending=False).iloc[0]

best_window=int(best.window)

# ---------- history best window ----------
best_hist=[r["history"] for r in results if r["window"]==best_window][0]

hist_df=pd.DataFrame(best_hist)

# ---------- live prediction ----------
pred=predict(groups,best_window)

# ---------- UI ----------

st.title("⚡ V49.1 Window Streak Engine (Fixed Backtest)")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",ROUNDS)
c2.metric("Best Window",best_window)
c3.metric("Trades",int(best.trades))

c4,c5,c6=st.columns(3)

c4.metric("Winrate",round(best.winrate*100,2))
c5.metric("Profit",round(best.profit,2))
c6.metric("Drawdown",round(best.drawdown,2))

# ---------- next group ----------

st.subheader("Next Group")

if pred:

    st.success(f"PREDICT → Group {pred}")

else:

    st.info("SKIP")

# ---------- equity curve ----------

st.subheader("Equity Curve")

st.line_chart(hist_df["profit"])

# ---------- window performance ----------

st.subheader("Window Performance")

st.dataframe(perf)

# ---------- history ----------

st.subheader("Trade History")

st.dataframe(hist_df.tail(100))
