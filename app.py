import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 14]

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
signal_created_at = None

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
        signal_created_at = None

    # ===== GENERATE HIGH QUALITY SIGNAL =====
    if len(engine) >= 40 and i - last_trade_round > 4:

        best_window = None
        best_ev = -999
        best_wr = 0

        for w in WINDOWS:

            recent_hits = []

            for j in range(len(engine) - 30, len(engine)):
                if j >= w:
                    if engine[j]["group"] == engine[j - w]["group"]:
                        recent_hits.append(1)
                    else:
                        recent_hits.append(0)

            if len(recent_hits) >= 20:
                wr = np.mean(recent_hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                if ev > best_ev:
                    best_ev = ev
                    best_window = w
                    best_wr = wr

        # Strict filter
        if best_window and best_wr > 0.31 and best_ev >= 0.1:

            next_signal = engine[-best_window]["group"]
            next_window = best_window
            next_wr = round(best_wr * 100, 2)
            next_ev = round(best_ev, 3)
            signal_created_at = i + 1
            state = "SIGNAL"

    engine.append({
        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state
    })

# ===== DASHBOARD =====

st.title("🟢 PRO SELECTIVE MODE")

col1, col2, col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit, 2))

hits = [x["hit"] for x in engine if x["hit"] is not None]

if hits:
    wr = np.mean(hits)
    col3.metric("Winrate %", round(wr * 100, 2))
else:
    col3.metric("Winrate %", 0)

if next_signal:
    st.markdown(f"""
    <div style='padding:15px;
                background:#1f4e79;
                color:white;
                border-radius:10px;
                text-align:center;
                font-size:24px;
                font-weight:bold'>
        🎯 NEXT GROUP: {next_signal}
        <br>Window: {next_window}
        <br>WR: {next_wr}%
        <br>EV: {next_ev}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Waiting for high-quality signal")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)
