import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,14))

st.set_page_config(layout="wide")

# ================= GROUP ================= #

def get_group(n):

    if 1 <= n <= 3:
        return 1
    if 4 <= n <= 6:
        return 2
    if 7 <= n <= 9:
        return 3
    if 10 <= n <= 12:
        return 4

    return None


# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()

numbers = df["number"].dropna().astype(int).tolist()

engine = []

total_profit = 0
last_trade_round = -999

next_signal = None

for i,n in enumerate(numbers):

    g = get_group(n)

    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    ev=None

    # ===== EXECUTE =====

    if next_signal is not None:

        predicted = next_signal

        hit = 1 if predicted==g else 0

        if hit:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS

        state="TRADE"

        next_signal=None
        last_trade_round=i

    # ===== GENERATE SIGNAL =====

    if len(engine) > 60 and i-last_trade_round>4:

        window_scores=[]

        for w in WINDOWS:

            hits=[]

            for j in range(w,len(engine)):

                if engine[j]["group"] == engine[j-w]["group"]:
                    hits.append(1)
                else:
                    hits.append(0)

            if len(hits)>30:

                wr=np.mean(hits)

                ev_calc = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS

                window_scores.append({
                    "window":w,
                    "wr":wr,
                    "ev":ev_calc
                })

        if len(window_scores)>0:

            window_scores = sorted(window_scores,key=lambda x:x["ev"],reverse=True)

            top = window_scores[:3]

            best = top[0]

            if best["wr"]>0.30 and best["ev"]>0:

                votes=[]

                for t in top:

                    w=t["window"]

                    votes.append(engine[-w]["group"])

                signal=max(set(votes),key=votes.count)

                if engine[-1]["group"] != signal:

                    next_signal = signal

                    state="SIGNAL"

                    window_used = best["window"]

                    ev = round(best["ev"],3)

    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "ev":ev,
        "state":state

    })

# ================= DASHBOARD ================= #

st.title("AI WINDOW ENGINE V2")

col1,col2,col3 = st.columns(3)

col1.metric("Total Rounds",len(engine))

col2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:
    wr=np.mean(hits)
    col3.metric("Winrate %",round(wr*100,2))
else:
    col3.metric("Winrate %",0)

# ================= NEXT ================= #

if next_signal is not None:

    st.markdown(f"""

    <div style='padding:25px;
                background:#b71c1c;
                color:white;
                font-size:30px;
                text-align:center;
                border-radius:10px'>

    NEXT GROUP TO BET

    <br><br>

    🎯 {next_signal}

    </div>

    """,unsafe_allow_html=True)

else:

    st.info("No signal")

# ================= HISTORY ================= #

st.subheader("History")

hist_df=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)
