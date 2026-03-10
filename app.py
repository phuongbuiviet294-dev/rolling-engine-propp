import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_MIN = 8
WINDOW_MAX = 17
LOOKBACK = 24
BASE_GAP = 1

st.set_page_config(layout="wide")

# ================= GROUP =================
def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

# ================= LOAD =================
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
next_window = None
next_wr = None
next_ev = None

loss_streak = 0

for i, n in enumerate(numbers):
    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    window_used = None
    wr_used = None
    ev_used = None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted = next_signal
        window_used = next_window
        wr_used = next_wr
        ev_used = next_ev

        hit = 1 if predicted == g else 0

        if hit:
            total_profit += WIN_PROFIT
            loss_streak = 0
        else:
            total_profit -= LOSE_LOSS
            loss_streak += 1

        state = "TRADE"
        last_trade_round = i
        next_signal = None

    # ===== MARKET REGIME =====
    recent_hits = [x["hit"] for x in engine[-15:] if x["hit"] is not None]
    wr_live = np.mean(recent_hits) if recent_hits else 0

    if wr_live > 0.34:
        regime = "HOT"
    elif wr_live > 0.28:
        regime = "WARM"
    else:
        regime = "COLD"

    # ===== GAP CONTROL =====
    GAP = BASE_GAP
    if loss_streak >= 2:
        GAP += 1
    if loss_streak >= 4:
        GAP += 1
    if loss_streak >= 6:
        GAP += 2

    # ===== GENERATE SIGNAL =====
    if len(engine) >= 25 and i - last_trade_round > GAP:
        best_window = None
        best_ev = -999
        best_wr = 0

        for w in range(WINDOW_MIN, WINDOW_MAX + 1):
            hits = []
            start = max(w, len(engine) - LOOKBACK)

            for j in range(start, len(engine)):
                if j >= w:
                    hits.append(
                        1 if engine[j]["group"] == engine[j - w]["group"] else 0
                    )

            if len(hits) >= 12:
                wr = np.mean(hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                if ev > best_ev:
                    best_ev = ev
                    best_window = w
                    best_wr = wr

        # ===== ENTRY FILTER =====
        if best_window is not None:
            wr_ok = best_wr > 0.28
            ev_ok = best_ev > 0

            # Regime filter
            if regime == "WARM":
                wr_ok = best_wr > 0.30
            if regime == "COLD":
                wr_ok = best_wr > 0.32
                ev_ok = best_ev > 0.05

            # Loss protection
            if loss_streak >= 4:
                ev_ok = best_ev > 0.08

            if wr_ok and ev_ok:
                g1 = engine[-best_window]["group"]
                if engine[-1]["group"] != g1:
                    next_signal = g1
                    next_window = best_window
                    next_wr = best_wr
                    next_ev = best_ev
                    state = "SIGNAL"

    engine.append({
        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "wr": wr_used,
        "ev": ev_used,
        "state": state
    })

# ================= DASHBOARD =================
st.title("⚡🛡 TURBO + RISK AI ENGINE")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Rounds", len(engine))
col2.metric("Profit", round(total_profit, 2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr_total = np.mean(hits) if hits else 0
col3.metric("Winrate %", round(wr_total * 100, 2))
col4.metric("Loss Streak", loss_streak)

st.caption(f"Adaptive Window {WINDOW_MIN}-{WINDOW_MAX} | Lookback={LOOKBACK} | Regime={regime}")

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>
        🚨 READY TO BET 🚨
        <br>🎯 NEXT GROUP: {next_signal}
        <br>Window: {next_window}
        <br>WR: {round(next_wr*100,2)}%
        <br>EV: {round(next_ev,3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Smart filter active — waiting setup")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
