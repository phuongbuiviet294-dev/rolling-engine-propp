import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = range(8, 19)  # dynamic windows
COOLDOWN = 2            # aggressive cooldown
EV_THRESHOLD = 0.1

st.set_page_config(layout="wide")

# ================= CORE ================= #

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

# ================= ENGINE ================= #

engine = []
total_profit = 0
last_trade_round = -999

next_signal = None
next_window = None
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
        next_window = None
        next_ev = None
        next_wr = None

    # ===== SCAN WINDOWS =====
    if len(engine) >= 40:

        best_window = None
        best_ev = -999
        best_wr = 0

        for w in WINDOWS:

            recent_hits = []

            for j in range(len(engine) - 30, len(engine)):
                if j >= w:
                    recent_hits.append(
                        1 if engine[j]["group"] == engine[j - w]["group"] else 0
                    )

            if len(recent_hits) >= 20:
                wr = np.mean(recent_hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                if ev > best_ev:
                    best_ev = ev
                    best_window = w
                    best_wr = wr

        # ===== AGGRESSIVE ENTRY =====
        if (
            best_window is not None
            and best_ev >= EV_THRESHOLD
            and i - last_trade_round > COOLDOWN
        ):
            next_signal = engine[-best_window]["group"]
            next_window = best_window
            next_ev = round(best_ev, 3)
            next_wr = round(best_wr * 100, 2)
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

st.title("🔥 FULL AGGRESSIVE EV ENGINE")

col1, col2, col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit, 2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
if hits:
    wr = np.mean(hits)
    col3.metric("Winrate %", round(wr * 100, 2))
else:
    col3.metric("Winrate %", 0)

# ===== NEXT GROUP DISPLAY =====

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;
                background:#cc0000;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>
        🚨 NEXT GROUP: {next_signal}
        <br>Window: {next_window}
        <br>WR: {next_wr}%
        <br>EV: {next_ev}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("No aggressive edge right now")

# ===== HISTORY =====

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)

st.caption("Dynamic Window 8–18 | Cooldown 2 | EV ≥ 0.1 | High Frequency Mode")
