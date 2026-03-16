import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=182
WINDOWS=[6,8,10,12,14]

GAP=4

WIN=2.5
LOSS=-1

# -------- GROUP --------
def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=8: return 3
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


# -------- TRADE ENGINE --------
profit=0
last_trade=-999

history=[]
hits=[]


for i in range(SCAN,len(groups)):

    preds=[groups[i-w] for w in WINDOWS if i-w>=0]

    c=Counter(preds)

    vote,confidence=c.most_common(1)[0]

    signal=False
    trade=False
    hit=None

    if confidence>=2:

        signal=True

        if groups[i-1]!=vote and (i-last_trade)>=GAP:

            trade=True

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
        "number":numbers[i],
        "group":groups[i],
        "vote":vote,
        "confidence":confidence,
        "signal":signal,
        "trade":trade,
        "hit":hit,
        "profit":profit
    })


hist=pd.DataFrame(history)


# -------- CURRENT --------
current_number=numbers[-1]
current_group=groups[-1]


preds=[groups[-w] for w in WINDOWS]

c=Counter(preds)

vote,confidence=c.most_common(1)[0]


# -------- UI --------
st.title("NEXT GROUP ENGINE")


st.subheader("Current")

st.write("Number:",current_number)

st.write("Group:",current_group)


if confidence>=2 and current_group!=vote:

    st.markdown(
    f"<h1 style='color:red'>BET GROUP {vote}</h1>",
    unsafe_allow_html=True
    )

else:

    st.markdown(
    "<h1 style='color:gray'>WAIT</h1>",
    unsafe_allow_html=True
    )


# -------- RESULT --------
st.subheader("Session Result")

col1,col2,col3=st.columns(3)

col1.metric("Profit",profit)

trades=len(hits)

col2.metric("Trades",trades)

wr=np.mean(hits) if trades>0 else 0

col3.metric("Winrate %",round(wr*100,2))


# -------- EQUITY --------
st.subheader("Equity Curve")

st.line_chart(hist.profit)


# -------- HISTORY --------
st.subheader("History")

st.dataframe(hist.iloc[::-1],use_container_width=True)
