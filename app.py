import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5
WIN_PROFIT=2.5
LOSE_LOSS=1

WINDOWS=[9,14]
LOOKBACK=80
COOLDOWN=3

REGIME_STOP=10

st.set_page_config(layout="wide")

def get_group(n):

    if 1<=n<=3:return 1
    if 4<=n<=6:return 2
    if 7<=n<=9:return 3
    if 10<=n<=12:return 4

    return None


@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df=load()

numbers=df["number"].dropna().astype(int).tolist()

engine=[]

total_profit=0
last_trade_round=-999

next_signal=None
next_window=None
next_wr=None
next_ev=None

retry_mode=False
miss_streak=0
pause_until=-1

preview_signal=None
preview_window=None
preview_wr=None
preview_ev=None


for i,n in enumerate(numbers):

    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    rolling_wr=None
    ev_value=None
    reason=None


# ===== EXECUTE =====

    if next_signal is not None:

        predicted=next_signal
        window_used=next_window
        rolling_wr=next_wr
        ev_value=next_ev

        hit=1 if predicted==g else 0

        if hit==1:

            total_profit+=WIN_PROFIT
            next_signal=None
            retry_mode=False
            miss_streak=0

        else:

            total_profit-=LOSE_LOSS
            miss_streak+=1

            if retry_mode==False:
                retry_mode=True
            else:
                next_signal=None
                retry_mode=False

        state="TRADE"
        last_trade_round=i

        if miss_streak>=2:

            pause_until=i+REGIME_STOP
            miss_streak=0


# ===== SCAN =====

    if (
        len(engine)>=LOOKBACK
        and i-last_trade_round>COOLDOWN
        and next_signal is None
        and i>pause_until
    ):

        best_window=None
        best_ev=-999
        best_wr=0

        for w in WINDOWS:

            hits=[]

            for j in range(len(engine)-LOOKBACK,len(engine)):

                if j>=w:

                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )

            if len(hits)>=40:

                wr=np.mean(hits)

                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

                if ev>best_ev:

                    best_ev=ev
                    best_window=w
                    best_wr=wr


# ===== PREVIEW =====

        if best_window and best_wr>0.30:

            preview_signal=engine[-best_window]["group"]
            preview_window=best_window
            preview_wr=round(best_wr*100,2)
            preview_ev=round(best_ev,3)


# ===== CONFIRM =====

        if best_window and best_wr>0.31 and best_ev>0:

            next_signal=engine[-best_window]["group"]
            next_window=best_window
            next_wr=round(best_wr*100,2)
            next_ev=round(best_ev,3)

            state="SIGNAL"
            reason=f"Window {best_window}"


    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":rolling_wr,
        "ev":ev_value,
        "state":state,
        "reason":reason

    })


st.title("🛡 QUANT SHIELD ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr=np.mean(hits)
    c3.metric("WR",round(wr*100,2))


if preview_signal:

    st.markdown(f"""
### 🔎 PREVIEW

Group: {preview_signal}

Window: {preview_window}

WR: {preview_wr}%

EV: {preview_ev}
""")


if next_signal:

    st.markdown(f"""
# 🚨 NEXT GROUP

## {next_signal}
""")


st.subheader("History")

hist=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist,use_container_width=True)
