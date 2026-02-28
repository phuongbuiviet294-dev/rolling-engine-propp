import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOW = 14
ROLLING_SAMPLE = 40
COOLDOWN = 2
EV_THRESHOLD = 0.12

st.set_page_config(layout="wide")

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

engine = []
total_profit = 0
last_trade_round = -999
next_signal = None
next_ev = None
next_wr = None

for i, n in enumerate(numbers):

    g = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"

    # ===== EXECUTE TRADE =====
    if next_signal is not None:

        predicted = next_signal
        hit = 1 if predicted == g else 0

        if hit == 1:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS

        state = "TRADE"
        last_trade_round = i
        next_signal = None
        next_ev = None
        next_wr = None

    # ===== SCAN WINDOW 14 =====
    if len(engine) >= WINDOW + ROLLING_SAMPLE:

        recent_hits = []

        for j in range(len(engine) - ROLLING_SAMPLE, len(engine)):
            if engine[j]["group"] == engine[j - WINDOW]["group"]:
                recent_hits.append(1)
            else:
                recent_hits.append(0)

        wr = np.mean(recent_hits)
        ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

        if ev >= EV_THRESHOLD and i - last_trade_round > COOLDOWN:
            next_signal = engine[-WINDOW]["group"]
            next_ev = round(ev, 3)
            next_wr = round(wr * 100, 2)
            state = "SIGNAL"

    engine.append({
        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state
    })

# ================= DASHBOARD ================= #

st.title("🎯 WINDOW 14 OPTIMIZED (Rolling 40)")

col1, col2, col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit, 2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
if hits:
    wr_total = np.mean(hits)
    col3.metric("Winrate %", round(wr_total * 100, 2))
else:
    col3.metric("Winrate %", 0)

# ===== SIGNAL DISPLAY =====

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;
                background:#cc0000;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
        🚨 NEXT GROUP: {next_signal}
        <br>WR: {next_wr}%
        <br>EV: {next_ev}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("No valid edge right now")

# ===== HISTORY =====

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)

st.caption("Window 14 | Rolling 40 | EV ≥ 0.12 | Cooldown 2")
