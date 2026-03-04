import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5
WIN_PROFIT=2.5
LOSE_LOSS=1

WINDOWS=list(range(6,21))

LOOKBACK=100
COOLDOWN=4

st.set_page_config(layout="wide")

# ================= CORE ================= #

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

# ================= ENGINE ================= #

engine=[]

profit=0
last_trade_round=-999

next_signal=None

current_wr=0
current_ev=0

last_hit_wr=0
last_hit_ev=0

preview=None

for i,n in enumerate(numbers):

    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"


# ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted=next_signal

        hit=1 if predicted==g else 0

        if hit==1:

            profit+=WIN_PROFIT

            last_hit_wr=current_wr
            last_hit_ev=current_ev

        else:

            profit-=LOSE_LOSS

            last_hit_wr=0
            last_hit_ev=0

        state="TRADE"

        last_trade_round=i

        next_signal=None


# ===== SEARCH SIGNAL =====

    if len(engine)>=LOOKBACK and i-last_trade_round>COOLDOWN:

        best_ev=-999
        best_wr=0
        best_group=None
        best_window=None

        for w in WINDOWS:

            hits=[]

            for j in range(len(engine)-LOOKBACK,len(engine)):

                if j>=w:

                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )

            if len(hits)>40:

                wr=np.mean(hits)

                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

                if ev>best_ev:

                    best_ev=ev
                    best_wr=wr
                    best_window=w
                    best_group=engine[-w]["group"]

        preview=(best_group,best_window,best_wr,best_ev)

        if (
            best_wr>0.30
            and best_ev>0
            and best_wr>last_hit_wr
            and best_ev>last_hit_ev
        ):

            next_signal=best_group

            current_wr=best_wr
            current_ev=best_ev

            state="SIGNAL"


    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state

    })


# ================= DASHBOARD ================= #

st.title("🎯 ADAPTIVE HIT BENCHMARK ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",len(engine))
c2.metric("Profit",round(profit,2))

hits=[x["hit"] for x in engine if x["hit"]!=None]

if hits:

    wr=np.mean(hits)

    c3.metric("Winrate %",round(wr*100,2))

else:

    c3.metric("Winrate %",0)


# ================= PREVIEW ================= #

if preview:

    g,w,wr,ev=preview

    st.markdown(f"""

    🔎 **Preview Signal**

    Group: {g}

    Window: {w}

    WR: {wr*100:.2f}%

    EV: {ev:.3f}

    """)


# ================= HISTORY ================= #

st.subheader("History")

hist_df=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)

st.caption("WINDOW 6-20 | HIT BENCHMARK FILTER")
