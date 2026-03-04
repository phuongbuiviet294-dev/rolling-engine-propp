import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

COOLDOWN = 2

st.set_page_config(layout="wide")

# ================= CORE =================

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None


@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)


df = load()

if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================

engine = []

total_profit = 0
last_trade_round = -999

next_signal = None
signal_created_at = None

preview_signal = None


for i, n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    reason = None

    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal

        hit = 1 if predicted == g else 0

        if hit == 1:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS

        state = "TRADE"
        reason = f"Executed signal from round {signal_created_at}"

        last_trade_round = i
        next_signal = None


    # ===== GENERATE SIGNAL =====

    if len(engine) >= 3 and i - last_trade_round > COOLDOWN:

        g1 = engine[-1]["group"]
        g2 = engine[-2]["group"]
        g3 = engine[-3]["group"]

        predicted_group = None

        # ===== STREAK LOGIC =====
        if g1 == g2 == g3:

            choices = [1,2,3,4]
            choices.remove(g1)

            predicted_group = np.random.choice(choices)

            reason = "STREAK BREAK"

        # ===== ANTI REPEAT =====
        else:

            choices = [1,2,3,4]
            choices.remove(g1)

            predicted_group = np.random.choice(choices)

            reason = "ANTI REPEAT"

        preview_signal = predicted_group

        next_signal = predicted_group
        signal_created_at = i + 1

        state = "SIGNAL"


    engine.append({

        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state,
        "reason": reason

    })


# ================= DASHBOARD =================

st.title("🔥 STREAK + ANTI ENGINE")

col1, col2, col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr = np.mean(hits)

    col3.metric("Winrate %", round(wr*100,2))

else:

    col3.metric("Winrate %", 0)


# ================= NEXT GROUP =================

if preview_signal is not None:

    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>

        🎯 NEXT GROUP: {preview_signal}

    </div>
    """, unsafe_allow_html=True)

else:

    st.info("No signal")


# ================= HISTORY =================

st.subheader("History")

hist_df = pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df, use_container_width=True)

st.caption("STREAK + ANTI ENGINE")
