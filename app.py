import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=182
WINDOW_MIN=6
WINDOW_MAX=20

WIN=2.5
LOSS=-1
GAP=4


# ---------------- GROUP ----------------

def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# ---------------- LOAD DATA ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()

groups=[group(n) for n in numbers]


# ---------------- WINDOW SCAN ----------------

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

top3=scan_df.head(3)["window"].tolist()
top5=scan_df.head(5)["window"].tolist()

st.subheader("Scan Result")
st.dataframe(scan_df)


# ---------------- ENGINE FUNCTION ----------------

def run_engine(windows, vote_need):

    profit=0
    last_trade=-999

    history=[]
    hits=[]

    for i in range(SCAN,len(groups)):

        preds=[groups[i-w] for w in windows]

        c=Counter(preds)

        vote,conf=c.most_common(1)[0]

        signal=False
        hit=None

        if conf>=vote_need and groups[i-1]!=vote and (i-last_trade)>=GAP:

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

    return profit,len(hits),wr,history


# ---------------- RUN 2 STRATEGIES ----------------

p1,t1,wr1,e1=run_engine(top3,2)

p2,t2,wr2,e2=run_engine(top5,3)


# ---------------- DASHBOARD ----------------

st.subheader("Strategy Compare")

col1,col2=st.columns(2)

with col1:

    st.write("### 3 vote 2")

    st.metric("Profit",round(p1,2))
    st.metric("Trades",t1)
    st.metric("Winrate",round(wr1*100,2))

with col2:

    st.write("### 5 vote 3")

    st.metric("Profit",round(p2,2))
    st.metric("Trades",t2)
    st.metric("Winrate",round(wr2*100,2))


# ---------------- EQUITY ----------------

st.subheader("Equity Compare")

df_equity=pd.DataFrame({
    "3vote2":e1,
    "5vote3":e2
})

st.line_chart(df_equity)
