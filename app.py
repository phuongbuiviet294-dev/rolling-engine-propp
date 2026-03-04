import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5
WIN_PROFIT=2.5
LOSE_LOSS=1

WINDOWS=[6,9,12,14,18]

LOOKBACK=80
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

if df.empty:
    st.stop()

numbers=df["number"].dropna().astype(int).tolist()

# ================= ENGINE ================= #

engine=[]
total_profit=0
last_trade_round=-999

next_signal=None
signal_created_at=None

preview_signal=None
preview_strength=None

for i,n in enumerate(numbers):

    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"
    reason=None


# ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted=next_signal

        hit=1 if predicted==g else 0

        if hit==1:
            total_profit+=WIN_PROFIT
        else:
            total_profit-=LOSE_LOSS

        state="TRADE"
        last_trade_round=i

        next_signal=None


# ===== SIGNAL GENERATION =====

    if len(engine)>=LOOKBACK and i-last_trade_round>COOLDOWN:

        votes={}
        weights={}

        for w in WINDOWS:

            hits=[]

            for j in range(len(engine)-LOOKBACK,len(engine)):

                if j>=w:

                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )

            if len(hits)>=30:

                wr=np.mean(hits)

                if wr>0.28:

                    group=engine[-w]["group"]

                    weight=wr

                    votes[group]=votes.get(group,0)+weight
                    weights[group]=wr


        if votes:

            best_group=max(votes,key=votes.get)

            preview_signal=best_group
            preview_strength=round(votes[best_group],3)

            if votes[best_group]>0.9:

                next_signal=best_group
                signal_created_at=i+1
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

st.title("⚡ QUANT ENSEMBLE ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr=np.mean(hits)
    c3.metric("Winrate %",round(wr*100,2))

else:

    c3.metric("Winrate %",0)


# ================= PREVIEW ================= #

if preview_signal is not None:

    st.markdown(f"""
    <div style='padding:15px;
                background:#444;
                color:white;
                border-radius:10px;
                text-align:center;
                font-size:22px'>

    🔎 PREVIEW GROUP: {preview_signal}

    <br>Signal Strength: {preview_strength}

    </div>
    """,unsafe_allow_html=True)


# ================= NEXT GROUP ================= #

if next_signal is not None:

    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:30px;
                font-weight:bold'>

    🚨 READY TO BET

    <br>🎯 GROUP: {next_signal}

    </div>
    """,unsafe_allow_html=True)

else:

    st.info("No valid signal yet")


# ================= HISTORY ================= #

st.subheader("History")

hist_df=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)

st.caption("ENSEMBLE WINDOWS 6/9/12/14/18")
