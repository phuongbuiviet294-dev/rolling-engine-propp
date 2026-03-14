import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=182
TARGET=10
STOP=-10

WIN=2.5
LOSS=-1


# ---------------- GROUP ----------------

def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# ---------------- LOAD ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()

groups=[group(n) for n in numbers]


# ---------------- PATTERN ENGINE ----------------

profit=0
last_trade=-999
GAP=4

history=[]
hits=[]

for i in range(SCAN,len(groups)):

    signal=False
    pred=None

    # ABAB pattern
    if groups[i-4]==groups[i-2] and groups[i-3]==groups[i-1]:

        pred=groups[i-2]
        signal=True


    # run break
    elif groups[i-3]==groups[i-2]==groups[i-1]:

        pred=None
        signal=False


    # repeat bias
    elif groups[i-1]==groups[i-2]:

        pred=groups[i-1]
        signal=True


    if signal and (i-last_trade)>=GAP:

        last_trade=i

        if groups[i]==pred:

            profit+=WIN
            hit=1
            hits.append(1)

        else:

            profit+=LOSS
            hit=0
            hits.append(0)

    else:

        hit=None

    history.append({
        "round":i,
        "group":groups[i],
        "pred":pred,
        "signal":signal,
        "hit":hit,
        "profit":profit
    })


    if profit>=TARGET or profit<=STOP:
        break


hist=pd.DataFrame(history)


# ---------------- RESULT ----------------

st.subheader("Pattern Engine Result")

col1,col2,col3=st.columns(3)

col1.metric("Profit",profit)

trades=hist.hit.count()

col2.metric("Trades",trades)

wr=np.mean(hits) if trades>0 else 0

col3.metric("Winrate %",round(wr*100,2))


st.subheader("Equity Curve")

st.line_chart(hist.profit)


st.subheader("History")

st.dataframe(hist.iloc[::-1])
