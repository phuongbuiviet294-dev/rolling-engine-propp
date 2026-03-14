import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN_SIZE=182
TRADE_SIZE=20

WINDOW_MIN=7
WINDOW_MAX=12

TOP_WINDOWS=3

GAP=4

TARGET=10
STOP=-10

WIN=2.5
LOSS=-1


# ---------- GROUP ----------

def group(n):

    if n<=3:
        return 1
    elif n<=6:
        return 2
    elif n<=9:
        return 3
    else:
        return 4


# ---------- LOAD DATA ----------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int).tolist()

    return numbers


numbers=load()

groups=[group(n) for n in numbers]


# ---------- WINDOW SCAN ----------

def scan_window(data):

    results=[]

    for w in range(WINDOW_MIN,WINDOW_MAX+1):

        profit=0
        trades=0
        wins=0

        for i in range(w,len(data)):

            pred=data[i-w]

            if data[i-1]!=pred:

                trades+=1

                if data[i]==pred:

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


    df=pd.DataFrame(results)

    df=df.sort_values("score",ascending=False)

    return df


# ---------- TRADE ENGINE ----------

profit=0

history=[]

i=0

while i<len(groups)-SCAN_SIZE:

    scan_data=groups[i:i+SCAN_SIZE]

    scan_df=scan_window(scan_data)

    top=scan_df.head(TOP_WINDOWS)

    windows=top.window.tolist()

    st.write("Top windows:",windows)

    last_trade=-999

    trade_end=i+SCAN_SIZE+TRADE_SIZE

    j=i+SCAN_SIZE

    while j<trade_end and j<len(groups):

        preds=[groups[j-w] for w in windows]

        vote=max(set(preds),key=preds.count)

        conf=preds.count(vote)

        signal=False
        hit=None

        if conf>=2 and groups[j-1]!=vote and (j-last_trade)>=GAP:

            signal=True

            last_trade=j

            if groups[j]==vote:

                profit+=WIN
                hit=1
            else:

                profit+=LOSS
                hit=0


        history.append({

            "round":j,
            "group":groups[j],
            "vote":vote,
            "conf":conf,
            "signal":signal,
            "hit":hit,
            "profit":profit

        })


        if profit>=TARGET or profit<=STOP:

            break

        j+=1


    if profit>=TARGET or profit<=STOP:

        break


    i+=TRADE_SIZE


hist=pd.DataFrame(history)


# ---------- DASHBOARD ----------

st.subheader("Session Result")

col1,col2,col3=st.columns(3)

col1.metric("Profit",profit)

col2.metric("Trades",hist.hit.count())

wr=hist.hit.mean() if hist.hit.count()>0 else 0

col3.metric("Winrate %",round(wr*100,2))


# ---------- EQUITY ----------

st.subheader("Equity Curve")

st.line_chart(hist.profit)


# ---------- HISTORY ----------

st.subheader("History")

st.dataframe(hist.iloc[::-1])
