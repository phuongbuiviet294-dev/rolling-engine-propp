import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1

BACKTEST_SIZE=2000

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

# ---------- ENGINE ----------

hits=[]
profit=0
history=[]
equity=[]

for i in range(9,len(groups)-1):

    pred=groups[i-9]
    actual=groups[i]

    hit=1 if pred==actual else 0
    hits.append(hit)

    signal=False

    if len(hits)>=2 and hits[-2:]==[1,1]:
        signal=True

    if len(hits)>=3 and hits[-3:]==[0,1,1]:
        signal=True

    state="SCAN"

    if signal:

        if hit:
            profit+=WIN
        else:
            profit-=LOSS

        state="TRADE"

    equity.append(profit)

    history.append({
        "round":i,
        "number":numbers[i],
        "group":groups[i],
        "hit":hit,
        "state":state,
        "profit":profit
    })

df_hist=pd.DataFrame(history)

# ---------- BACKTEST / LIVE ----------

backtest=df_hist[df_hist["round"]<=BACKTEST_SIZE]
live=df_hist[df_hist["round"]>BACKTEST_SIZE]

profit_backtest=backtest["profit"].iloc[-1] if len(backtest)>0 else 0
profit_live=live["profit"].iloc[-1]-profit_backtest if len(live)>0 else 0

# ---------- NEXT SIGNAL ----------

next_signal=False

if len(hits)>=2 and hits[-2:]==[1,1]:
    next_signal=True

if len(hits)>=3 and hits[-3:]==[0,1,1]:
    next_signal=True

next_group=groups[-9]

# ---------- DASHBOARD ----------

st.title("Pattern Engine Backtest + Live")

c1,c2,c3=st.columns(3)

c1.metric("Backtest Profit",round(profit_backtest,2))
c2.metric("Live Profit",round(profit_live,2))
c3.metric("Total Profit",round(profit,2))

# ---------- SIGNAL ----------

st.subheader("Next Signal")

if next_signal:
    st.success(f"BET GROUP → {next_group}")
else:
    st.info("WAIT")

# ---------- EQUITY ----------

st.subheader("Equity Curve")

st.line_chart(df_hist["profit"])

# ---------- HISTORY ----------

st.subheader("History")

st.dataframe(df_hist.iloc[::-1],use_container_width=True)
