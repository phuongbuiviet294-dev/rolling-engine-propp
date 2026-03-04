import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5
WIN_PROFIT=2.5
LOSE_LOSS=1

WINDOWS=list(range(6,31))
LOOKBACK=120
COOLDOWN=6

st.set_page_config(layout="wide")

def get_group(n):
    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4
    return None

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df=load()
numbers=df["number"].dropna().astype(int).tolist()

engine=[]
profit=0
last_trade_round=-999
next_signal=None

preview=None

for i,n in enumerate(numbers):

    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"

    # EXECUTE
    if next_signal is not None:
        predicted=next_signal
        hit=1 if predicted==g else 0

        if hit:
            profit+=WIN_PROFIT
        else:
            profit-=LOSE_LOSS

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # SIGNAL SEARCH
    if len(engine)>=LOOKBACK and i-last_trade_round>COOLDOWN:

        best_ev=-999
        best_group=None
        best_window=None
        best_wr=0

        for w in WINDOWS:

            hits=[]
            for j in range(len(engine)-LOOKBACK,len(engine)):
                if j>=w:
                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )

            if len(hits)>50:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

                if ev>best_ev:
                    best_ev=ev
                    best_window=w
                    best_group=engine[-w]["group"]
                    best_wr=wr

        preview=(best_group,best_window,best_wr,best_ev)

        if best_ev>=0.3 and best_wr>=0.40:
            next_signal=best_group
            state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state
    })

# DASHBOARD
st.title("🎯 SNIPER ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(profit,2))

hits=[x["hit"] for x in engine if x["hit"]!=None]
if hits:
    wr=np.mean(hits)
    c3.metric("Winrate %",round(wr*100,2))

# PREVIEW
if preview:
    g,w,wr,ev=preview
    st.markdown(f"""
    **Preview Signal**

    Group: {g}  
    Window: {w}  
    WR: {wr*100:.2f}%  
    EV: {ev:.3f}
    """)

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
