import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=182
WINDOW_MIN=6
WINDOW_MAX=20

GAP=4

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

    df["number"]=pd.to_numeric(df["number"],errors="coerce")

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
            "score":score
        })


scan_df=pd.DataFrame(results).sort_values("score",ascending=False)

top_windows=scan_df.head(3)["window"].tolist()


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
    trade=False
    bet_group=None
    hit=None


    # signal detection
    if confidence>=2 and groups[i-1]!=vote:

        signal=True


    # trade condition
    if signal and (i-last_trade)>=GAP:

        trade=True
        bet_group=vote

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

        "bet_group":bet_group,
        "hit":hit,

        "profit":profit
    })


hist=pd.DataFrame(history)


# -------- LIVE NEXT SIGNAL --------

i=len(groups)

preds=[groups[i-w] for w in top_windows]

c=Counter(preds)

vote,confidence=c.most_common(1)[0]

distance=i-last_trade

current_number=numbers[-1]
current_group=groups[-1]


st.title("🎯 LIVE SIGNAL")

col1,col2=st.columns(2)

col1.metric("Current Number",current_number)
col2.metric("Current Group",current_group)

st.divider()


if confidence>=2 and groups[-1]!=vote and distance>=GAP:

    st.markdown(
        f"""
        <div style="
        background-color:#ff4b4b;
        padding:25px;
        border-radius:12px;
        text-align:center;
        color:white;
        font-size:32px;
        font-weight:bold;">
        BET GROUP {vote}
        </div>
        """,
        unsafe_allow_html=True
    )

    st.write(f"Next Round Signal | Confidence {confidence}/3")

else:

    st.markdown(
        """
        <div style="
        background-color:#eeeeee;
        padding:20px;
        border-radius:10px;
        text-align:center;
        font-size:24px;">
        WAIT SIGNAL
        </div>
        """,
        unsafe_allow_html=True
    )


# -------- SESSION RESULT --------

st.subheader("Session Result")

col1,col2,col3=st.columns(3)

col1.metric("Profit",profit)

trades=len(hits)

col2.metric("Trades",trades)

wr=np.mean(hits) if trades>0 else 0

col3.metric("Winrate %",round(wr*100,2))


# -------- EQUITY --------

st.subheader("Equity Curve")

if len(hist)>0:

    st.line_chart(hist["profit"])


# -------- HISTORY --------

st.subheader("History")

st.dataframe(

    hist.iloc[::-1][[
        "round",
        "number",
        "group",
        "vote",
        "confidence",
        "signal",
        "trade",
        "bet_group",
        "hit",
        "profit"
    ]]

)
