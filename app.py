import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1

WINDOW_RANGE=range(6,21)
STEP=200

st.set_page_config(layout="wide")

# ---------- GROUP ----------

def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ---------- LOAD ----------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()
groups=[group(n) for n in numbers]

# ---------- SIM ----------

def simulate(data,window):

    profit=0

    for i in range(window,len(data)):

        pred=data[i-window]
        actual=data[i]

        if pred==actual:
            profit+=WIN
        else:
            profit-=LOSS

    return profit

# ---------- FIND BEST WINDOWS ----------

def best_windows(train):

    scores=[]

    for w in WINDOW_RANGE:

        p=simulate(train,w)

        scores.append((w,p))

    scores.sort(key=lambda x:x[1],reverse=True)

    return [x[0] for x in scores[:3]]

# ---------- WALK FORWARD ----------

profit=0
equity=[]
history=[]
hits=[]

start=2000
windows=[9]

for t in range(start,len(groups),STEP):

    train=groups[:t]

    windows=best_windows(train)

    end=min(t+STEP,len(groups))

    for i in range(t,end):

        preds=[groups[i-w] for w in windows]

        vote=max(set(preds),key=preds.count)

        vote_count=preds.count(vote)

        predicted=None
        hit=None
        state="SCAN"

        if vote_count>=2:

            predicted=vote

            actual=groups[i]

            hit=1 if predicted==actual else 0

            hits.append(hit)

            if hit:
                profit+=WIN
            else:
                profit-=LOSS

            state="TRADE"

        equity.append(profit)

        history.append({
            "round":i,
            "windows":windows,
            "predicted":predicted,
            "actual":groups[i],
            "hit":hit,
            "profit":profit
        })

# ---------- NEXT GROUP ----------

preds=[groups[-w] for w in windows]

vote=max(set(preds),key=preds.count)

vote_count=preds.count(vote)

next_group=vote if vote_count>=2 else None

# ---------- METRICS ----------

trades=len([h for h in hits if h is not None])
wins=hits.count(1)

wr=wins/trades if trades else 0

# ---------- DASHBOARD ----------

st.title("Adaptive Multi-Window Engine")

c1,c2,c3=st.columns(3)

c1.metric("Profit",round(profit,2))
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))

st.write("Active Windows:",windows)

# ---------- NEXT SIGNAL ----------

st.subheader("Next Bet")

if next_group:
    st.success(f"BET GROUP → {next_group}")
else:
    st.info("Waiting signal")

# ---------- EQUITY ----------

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"profit":equity}))

# ---------- HISTORY ----------

st.subheader("History")

st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
