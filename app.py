import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = range(8, 19)
ROLLING_SAMPLE = 35
WR_THRESHOLD = 0.35
EV_THRESHOLD = 0.15
COOLDOWN = 2

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
next_window = None
next_wr = None
next_ev = None

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
        next_window = None
        next_wr = None
        next_ev = None

    # ===== REGIME SCAN =====
    if len(engine) >= max(WINDOWS) + ROLLING_SAMPLE:

        best_window = None
        best_wr = 0
        best_ev = -999

        for w in WINDOWS:

            hits = []

            for j in range(len(engine) - ROLLING_SAMPLE, len(engine)):
                if engine[j]["group"] == engine[j - w]["group"]:
                    hits.append(1)
                else:
                    hits.append(0)

            wr = np.mean(hits)
            ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

            if wr > best_wr:
                best_wr = wr
                best_ev = ev
                best_window = w

        # ===== STRONG REGIME ENTRY =====
        if (
            best_window is not None
            and best_wr >= WR_THRESHOLD
            and best_ev >= EV_THRESHOLD
            and i - last_trade_round > COOLDOWN
        ):
            next_signal = engine[-best_window]["group"]
            next_window = best_window
            next_wr = round(best_wr * 100, 2)
            next_ev = round(best_ev, 3)
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

st.title("🔥 REGIME DETECTION ENGINE")

col1, col2, col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit, 2))

hits_total = [x["hit"] for x in engine if x["hit"] is not None]
if hits_total:
    wr_total = np.mean(hits_total)
    col3.metric("Winrate %", round(wr_total * 100, 2))
else:
    col3.metric("Winrate %", 0)

# ===== SIGNAL DISPLAY =====

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:25px;
                background:#cc0000;
                color:white;
                border-radius:14px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>
        🚨 STRONG REGIME DETECTED
        <br>NEXT GROUP: {next_signal}
        <br>Window: {next_window}
        <br>WR: {next_wr}%
        <br>EV: {next_ev}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("No strong regime right now")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)

st.caption("Dynamic Window 8–18 | WR ≥ 35% | EV ≥ 0.15 | Regime Only Mode")
