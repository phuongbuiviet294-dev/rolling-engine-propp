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

    df["number"]=pd.to_numeric(df["number"],errors="coerce")

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

top_windows=scan_df.head(3)["window"].tolist()


# ---------- NEXT GROUP ----------
i=len(groups)

preds=[groups[i-w] for w in top_windows]

vote,confidence=Counter(preds).most_common(1)[0]


# ---------- CURRENT ----------
current_number=numbers[-1]
current_group=groups[-1]


# ---------- UI ----------
st.title("🎯 NEXT BET")

col1,col2=st.columns(2)

col1.metric("Current Number",current_number)
col2.metric("Current Group",current_group)

st.divider()

if confidence>=2 and current_group!=vote:

    st.markdown(
        f"""
        <div style="
        background:#ff4b4b;
        padding:25px;
        border-radius:10px;
        text-align:center;
        font-size:32px;
        color:white;
        font-weight:bold;">
        NEXT GROUP → {vote}
        </div>
        """,
        unsafe_allow_html=True
    )

else:

    st.markdown(
        """
        <div style="
        background:#eeeeee;
        padding:20px;
        border-radius:10px;
        text-align:center;
        font-size:24px;">
        WAIT
        </div>
        """,
        unsafe_allow_html=True
    )


# ---------- TOP WINDOWS ----------
st.subheader("Top Windows")

st.dataframe(scan_df.head(5))
