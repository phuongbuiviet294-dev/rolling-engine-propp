import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=182
WINDOW_MIN=6
WINDOW_MAX=20

GAP=4

TARGET=10
STOP=-10

WIN=2.5
LOSS=-1


# -------- GROUP --------

def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# -------- LOAD DATA --------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int).tolist()

    return numbers


numbers=load()

groups=[group(n) for n in numbers]


# -------- WINDOW SCAN --------

scan_groups=groups[:SCAN]

results=[]

for w in range(WINDOW_MIN,WINDOW_MAX+1):

    profit=0
    trades=0
    wins=0

    for i in range(w,len(scan_groups)):

        pred=scan_groups[i-w]

        if scan_groups[i-1]!=pred:

            trades+=1

            if scan_groups[i]==pred:

                profit+=WIN
                wins+=1

            else:

                profit+=LOSS

    if trades>10:

        wr=wins/trades

        score=profit*wr*np.log(trades)

        results.append({
            "window":w,
            "profit":profit,
            "trades":trades,
            "winrate":wr,
            "score":score
        })


scan_df=pd.DataFrame(results).sort_values("score",ascending=False)

TOP=scan_df.head(3)

top_windows=TOP["window"].tolist()

st.subheader("Top Windows")

st.dataframe(TOP)


# -------- TRADE ENGINE --------

profit=0
last_trade=-999

history=[]
hits=[]

for i in range(SCAN,len(groups)):

    preds=[groups[i-w] for w in top_windows]

    c=Counter(preds)

    vote,confidence=c.most_common(1)[0]

    signal=False
    hit=None

    if confidence>=2 and groups[i-1]!=vote and (i-last_trade)>=GAP:

        signal=True

        last_trade=i

        if groups[i]==vote:

            profit+=WIN
            hit=1
            hits.append(1)

        else:

            profit+=LOSS
            hit=0
            hits.append(0)

    history.append({
        "round":i,
        "group":groups[i],
        "predictions":preds,
        "vote":vote,
        "confidence":confidence,
        "signal":signal,
        "hit":hit,
        "profit":profit
    })

    if profit>=TARGET or profit<=STOP:
        break


hist=pd.DataFrame(history)


# -------- RESULT --------

st.subheader("Session Result")

col1,col2,col3=st.columns(3)

col1.metric("Profit",profit)

trades=len(hits)

col2.metric("Trades",trades)

wr=np.mean(hits) if trades>0 else 0

col3.metric("Winrate %",round(wr*100,2))


st.subheader("Equity Curve")

st.line_chart(hist.profit)


# -------- NEXT SIGNAL --------

preds=[groups[-w] for w in top_windows]

c=Counter(preds)

vote,confidence=c.most_common(1)[0]

st.subheader("Next Signal")

if confidence>=2 and groups[-1]!=vote:

    st.success(f"BET GROUP {vote}")

else:

    st.info("WAIT")


st.subheader("History")

st.dataframe(hist.iloc[::-1])
