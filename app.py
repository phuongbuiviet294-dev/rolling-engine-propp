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


def group(n):

    if n<=3:
        return 1
    elif n<=6:
        return 2
    elif n<=9:
        return 3
    else:
        return 4


@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()
groups=[group(n) for n in numbers]


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


profit=0
history=[]

i=0

while i < len(groups)-SCAN_SIZE:

    scan_data=groups[i:i+SCAN_SIZE]

    scan_df=scan_window(scan_data)

    top=scan_df.head(TOP_WINDOWS)

    windows=top.window.tolist()

    last_trade=-999

    j=i+SCAN_SIZE
    end=j+TRADE_SIZE

    while j<end and j<len(groups):

        preds=[groups[j-w] for w in windows]

        vote=max(set(preds),key=preds.count)
        conf=preds.count(vote)

        signal=False
        hit=None

        if conf>=2:

            if groups[j-1]!=vote:

                if j-last_trade>=GAP:

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
            "vote":vote,
            "confidence":conf,
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


st.metric("Profit",profit)
st.metric("Trades",hist.hit.count())

wr=hist.hit.mean() if hist.hit.count()>0 else 0
st.metric("Winrate",round(wr*100,2))

st.line_chart(hist.profit)
