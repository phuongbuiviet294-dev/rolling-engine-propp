import streamlit as st
import pandas as pd
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

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

ROUNDS=len(groups)

# ---------- predict ----------
def predict(g,window):

    if len(g)<window:
        return None

    w=g[-window:]

    c=Counter(w)

    return max(c,key=c.get)

# ---------- streak probability ----------
def streak_prob(hits):

    total=0
    win=0

    for i in range(len(hits)-2):

        if hits[i]==1 and hits[i+1]==1:

            total+=1

            if hits[i+2]==1:
                win+=1

    if total<20:
        return None

    return win/total

# ---------- momentum ----------
def momentum(profit_history):

    if len(profit_history)<40:
        return 0

    p20=profit_history[-20]
    p40=profit_history[-40]

    return 1 if p20>p40 else 0

# ---------- backtest ----------
results=[]

for window in range(8,18):

    profit=0
    peak=0
    dd=0

    trades=0
    wins=0

    hits=[]
    profit_hist=[]

    history=[]

    for i in range(window,ROUNDS-1):

        prob=streak_prob(hits)

        mom=momentum(profit_hist)

        trade=False

        confidence=0

        if len(hits)>=2 and hits[-2:]==[1,1] and prob:

            confidence=0.4*prob + 0.3*mom + 0.3*0.25

            if confidence>0.4:

                trade=True

        pred=predict(groups[:i],window)

        if pred is None:
            continue

        actual=groups[i]

        hit=1 if pred==actual else 0

        if trade:

            trades+=1

            if hit:

                profit+=2.5
                wins+=1

            else:

                profit-=1

        hits.append(hit)

        profit_hist.append(profit)

        peak=max(peak,profit)

        dd=max(dd,peak-profit)

        history.append({

            "round":i,
            "pred":pred,
            "actual":actual,
            "hit":hit,
            "trade":trade,
            "profit":profit,
            "confidence":confidence
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

hist=[r["history"] for r in results if r["window"]==best_window][0]

hist_df=pd.DataFrame(hist)

# ---------- live ----------
live_pred=predict(groups,best_window)

# ---------- UI ----------
st.title("⚡ V51 Momentum Adaptive Engine")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",ROUNDS)
c2.metric("Best Window",best_window)
c3.metric("Trades",int(best.trades))

c4,c5,c6=st.columns(3)

c4.metric("Winrate",round(best.winrate*100,2))
c5.metric("Profit",round(best.profit,2))
c6.metric("Drawdown",round(best.drawdown,2))

st.subheader("Next Group")

if live_pred:

    st.success(f"PREDICT → Group {live_pred}")

else:

    st.info("SKIP")

st.subheader("Equity Curve")

st.line_chart(hist_df["profit"])

st.subheader("Window Performance")

st.dataframe(perf)

st.subheader("Trade History")

st.dataframe(hist_df.tail(100))
