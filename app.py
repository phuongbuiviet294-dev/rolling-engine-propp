import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=168
WINDOW_MIN=6
WINDOW_MAX=20

GAP=4

WIN=2.5
LOSS=-1


def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=8: return 3
    return 4


@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int).tolist()

    return numbers


numbers=load()

groups=[group(n) for n in numbers]


# -------- SCAN WINDOW --------

scan_groups=groups[:SCAN]

results=[]

for w in range(WINDOW_MIN,WINDOW_MAX+1):

    profit=0
    trades=0

    for i in range(w,len(scan_groups)):

        pred=scan_groups[i-w]

        if scan_groups[i-1]!=pred:

            trades+=1

            if scan_groups[i]==pred:

                profit+=WIN
            else:
                profit+=LOSS


    if trades>10:

        results.append({

            "window":w,
            "profit":profit,
            "trades":trades
        })


scan_df=pd.DataFrame(results)

LOCK_WINDOW=scan_df.sort_values("profit",ascending=False).iloc[0]["window"]


# -------- TRADE --------

profit=0
last_trade=-999

history=[]
hits=[]


for i in range(SCAN,len(groups)):

    pred=groups[i-LOCK_WINDOW]

    signal=False
    trade=False
    hit=None


    if pred!=groups[i-1] and (i-last_trade)>=GAP:

        signal=True

        trade=True

        last_trade=i

        if groups[i]==pred:

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
        "predict":pred,
        "signal":signal,
        "trade":trade,
        "hit":hit,
        "profit":profit
    })


hist=pd.DataFrame(history)


# -------- NEXT SIGNAL --------

current_group=groups[-1]

next_pred=groups[-LOCK_WINDOW]


st.title("LOCK WINDOW ENGINE")

st.write("Lock Window:",LOCK_WINDOW)

st.write("Current Group:",current_group)

if next_pred!=current_group:

    st.markdown(f"<h1 style='color:red'>BET GROUP {next_pred}</h1>",unsafe_allow_html=True)

else:

    st.markdown("<h1 style='color:gray'>WAIT</h1>",unsafe_allow_html=True)


# RESULT

st.metric("Profit",profit)

st.metric("Trades",len(hits))

wr=np.mean(hits) if hits else 0

st.metric("Winrate %",round(wr*100,2))


st.line_chart(hist.profit)

st.dataframe(hist.iloc[::-1])
