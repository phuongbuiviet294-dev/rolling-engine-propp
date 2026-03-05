import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5

WINDOWS = [6,7,8,9,10,11,12,14]

COOLDOWN = 4

P1_THRESHOLD = 0.42
P2_THRESHOLD = 0.55

st.set_page_config(layout="wide")


# ---------------- GROUP ---------------- #

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


# ---------------- LOAD ---------------- #

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()

numbers = df["number"].dropna().astype(int).tolist()


# ---------------- ENGINE ---------------- #

engine = []

total_profit = 0

last_trade_round = -999

next_groups = None
bet_mode = None


for i,n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"


    # ===== EXECUTE TRADE =====

    if next_groups is not None:

        predicted = next_groups

        if g in predicted:

            hit = 1

            if bet_mode == "1G":
                total_profit += 2.5
            else:
                total_profit += 1.5

        else:

            hit = 0
            total_profit -= 1


        state = "TRADE"

        last_trade_round = i

        next_groups = None
        bet_mode = None


    # ===== SIGNAL =====

    if len(engine) > 60 and i-last_trade_round > COOLDOWN:

        probs = {1:0,2:0,3:0,4:0}

        for w in WINDOWS:

            if len(engine) > w:

                grp = engine[-w]["group"]

                weight = 1/w

                probs[grp] += weight


        total = sum(probs.values())

        if total > 0:

            for k in probs:
                probs[k] /= total


            sorted_groups = sorted(probs.items(), key=lambda x: x[1], reverse=True)

            g1,p1 = sorted_groups[0]
            g2,p2 = sorted_groups[1]


            # ---- BET 1 GROUP ---- #

            if p1 >= P1_THRESHOLD:

                next_groups = [g1]
                bet_mode = "1G"
                state = "SIGNAL"


            # ---- BET 2 GROUP ---- #

            elif (p1+p2) >= P2_THRESHOLD:

                next_groups = [g1,g2]
                bet_mode = "2G"
                state = "SIGNAL"


    engine.append({

        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "mode": bet_mode,
        "state": state

    })


# ---------------- DASHBOARD ---------------- #

st.title("🧠 HYBRID QUANT ENGINE")

col1,col2,col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr = np.mean(hits)

    col3.metric("Winrate %", round(wr*100,2))

else:

    col3.metric("Winrate %",0)


# ---------------- NEXT GROUP ---------------- #

if next_groups:

    st.markdown(f"""
    <div style='padding:25px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>

        🎯 NEXT GROUP TO BET

        <br><br>{next_groups}

    </div>
    """, unsafe_allow_html=True)

else:

    st.info("Scanning market...")


# ---------------- HISTORY ---------------- #

st.subheader("History")

hist_df = pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)
