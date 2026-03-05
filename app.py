import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG ================= #

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(6,21))

AUTO_REFRESH = 5

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


# ================= LOAD DATA ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load_data():

    df = pd.read_csv(GOOGLE_SHEET_CSV)

    return df


df = load_data()

numbers = df["number"].dropna().astype(int).tolist()


# ================= AI PREDICTOR ================= #

def ai_predict(groups):

    if len(groups) < 30:
        return None

    seq = groups[-3:]

    counts = {1:0,2:0,3:0,4:0}

    for i in range(len(groups)-3):

        if groups[i:i+3] == seq:

            nxt = groups[i+3]

            counts[nxt]+=1

    total = sum(counts.values())

    if total == 0:
        return None

    probs = {k:v/total for k,v in counts.items()}

    best = max(probs,key=probs.get)

    if probs[best] > 0.35:

        return best

    return None


# ================= ENGINE ================= #

engine = []

groups = []

total_profit = 0

next_signal = None

for i,n in enumerate(numbers):

    g = get_group(n)

    groups.append(g)

    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    wr=None
    ev=None

    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal

        hit = 1 if predicted==g else 0

        if hit:

            total_profit += WIN_PROFIT

        else:

            total_profit -= LOSE_LOSS

        state="TRADE"

        next_signal=None


    # ===== WINDOW SCAN =====

    best_window=None
    best_wr=0
    best_ev=-999

    if len(groups)>80:

        for w in WINDOWS:

            hits=[]

            for j in range(w,len(groups)-1):

                if groups[j]==groups[j-w]:

                    hits.append(1)

                else:

                    hits.append(0)

            if len(hits)>30:

                wr=np.mean(hits)

                ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS

                if ev>best_ev:

                    best_ev=ev
                    best_window=w
                    best_wr=wr


    # ===== AI =====

    ai_group = ai_predict(groups)


    # ===== SIGNAL =====

    if best_window is not None:

        if best_wr>0.34 and best_ev>0:

            signal = groups[-1]

            if ai_group is not None:

                signal = ai_group

            next_signal = signal

            state="SIGNAL"

            window_used = best_window

            wr = round(best_wr*100,2)

            ev = round(best_ev,3)


    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":wr,
        "ev":ev,
        "state":state

    })


# ================= DASHBOARD ================= #

st.title("🎯 AI STREAMLIT BETTING ENGINE")


col1,col2,col3 = st.columns(3)

col1.metric("Total Rounds",len(engine))

col2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:

    col3.metric("Winrate %",round(np.mean(hits)*100,2))

else:

    col3.metric("Winrate %",0)


# ================= NEXT GROUP ================= #

if next_signal is not None:

    st.markdown(f"""

    <div style='
    padding:30px;
    background:#b71c1c;
    color:white;
    font-size:32px;
    text-align:center;
    border-radius:12px;
    font-weight:bold'>

    NEXT GROUP TO BET

    <br><br>

    🎯 {next_signal}

    </div>

    """,unsafe_allow_html=True)

else:

    st.info("No signal")


# ================= HISTORY ================= #

st.subheader("History")

hist_df = pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)
