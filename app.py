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


# ---------- GROUP ----------
def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
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

windows=scan_df["window"].tolist()


# ---------- ENGINE FUNCTION ----------

def run_engine(top_windows, vote_need):

    profit=0
    hits=[]
    last_trade=-999
    history=[]

    for i in range(SCAN,len(groups)):

        preds=[groups[i-w] for w in top_windows]

        c=Counter(preds)

        vote,confidence=c.most_common(1)[0]

        signal=False
        hit=None

        if confidence>=vote_need and groups[i-1]!=vote and (i-last_trade)>=GAP:

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

        history.append(profit)

    wr=np.mean(hits) if len(hits)>0 else 0

    preds=[groups[-w] for w in top_windows]

    c=Counter(preds)

    vote,confidence=c.most_common(1)[0]

    next_signal=None

    if confidence>=vote_need and groups[-1]!=vote:

        next_signal=vote

    return profit,len(hits),wr,history,next_signal


# ---------- RUN ENGINES ----------

profit3,trades3,wr3,eq3,next3=run_engine(windows[:3],2)

profit5,trades5,wr5,eq5,next5=run_engine(windows[:5],2)

profit6,trades6,wr6,eq6,next6=run_engine(windows[:6],3)


# ---------- DASHBOARD ----------

st.title("⚡ Multi Engine Live Comparison")

col1,col2,col3=st.columns(3)

with col1:

    st.subheader("3 Vote 2")

    st.metric("Profit",round(profit3,2))

    st.metric("Trades",trades3)

    st.metric("Winrate",round(wr3*100,2))

    if next3:

        st.error(f"BET GROUP {next3}")

    else:

        st.info("WAIT")


with col2:

    st.subheader("5 Vote 2")

    st.metric("Profit",round(profit5,2))

    st.metric("Trades",trades5)

    st.metric("Winrate",round(wr5*100,2))

    if next5:

        st.error(f"BET GROUP {next5}")

    else:

        st.info("WAIT")


with col3:

    st.subheader("6 Vote 3")

    st.metric("Profit",round(profit6,2))

    st.metric("Trades",trades6)

    st.metric("Winrate",round(wr6*100,2))

    if next6:

        st.error(f"BET GROUP {next6}")

    else:

        st.info("WAIT")


# ---------- EQUITY ----------

st.subheader("Equity Curve")

df=pd.DataFrame({
    "3_vote2":eq3,
    "5_vote2":eq5,
    "6_vote3":eq6
})

st.line_chart(df)
