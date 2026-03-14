import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=120
GAP=4

TARGET=10
STOP=-10

WIN=2.5
LOSS=-1

WINDOW_RANGE=range(6,20)

st.set_page_config(layout="wide")

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


# ---------------- SCAN WINDOW ----------------

scan_groups=groups[:SCAN]

results=[]

for w in WINDOW_RANGE:

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


    if trades>5:

        wr=wins/trades

        score=profit*wr*np.log(trades)

        results.append({

            "window":w,
            "profit":profit,
            "trades":trades,
            "winrate":wr,
            "score":score

        })


scan_df=pd.DataFrame(results)

scan_df=scan_df.sort_values("score",ascending=False)

LOCK_WINDOW=int(scan_df.iloc[0].window)


st.subheader("Window Scan Result")

st.dataframe(scan_df)

st.write("LOCK WINDOW:",LOCK_WINDOW)


# ---------------- TRADE ENGINE ----------------

profit=0
last_trade=-999

history=[]

for i in range(SCAN,len(groups)):

    pred=groups[i-LOCK_WINDOW]

    state="WAIT"
    hit=None

    if i-last_trade>=GAP and groups[i-1]!=pred:

        last_trade=i
        state="TRADE"

        if groups[i]==pred:

            profit+=WIN
            hit=1

        else:

            profit+=LOSS
            hit=0


    history.append({

        "round":i,
        "group":groups[i],
        "pred":pred,
        "hit":hit,
        "profit":profit,
        "state":state

    })


    if profit>=TARGET:
        break

    if profit<=STOP:
        break


hist=pd.DataFrame(history)


# ---------------- DASHBOARD ----------------

st.subheader("Session Result")

col1,col2,col3=st.columns(3)

col1.metric("Profit",profit)

col2.metric("Trades",hist.hit.count())

wr=hist.hit.mean() if hist.hit.count()>0 else 0

col3.metric("Winrate",round(wr*100,2))


# ---------------- EQUITY ----------------

st.subheader("Equity Curve")

st.line_chart(hist.profit)


# ---------------- SIGNAL ----------------

pred=groups[-LOCK_WINDOW]

st.subheader("Next Signal")

if groups[-1]!=pred:

    st.success(f"BET GROUP {pred}")

else:

    st.info("WAIT")


# ---------------- HISTORY ----------------

st.subheader("History")

st.dataframe(hist.iloc[::-1])
