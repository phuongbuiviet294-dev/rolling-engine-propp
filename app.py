import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOW_RANGE = range(8, 18)

LIVE_LOOKBACK = 120      # chỉ nhìn gần nhất
MIN_SAMPLE = 30
BASE_GAP = 3

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

# ================= REGIME DETECTOR =================
def detect_regime(wr_series):
    if len(wr_series) < 10:
        return "WARMUP"

    mean_wr = np.mean(wr_series[-10:])
    std_wr = np.std(wr_series[-10:])

    if mean_wr > 0.34 and std_wr < 0.08:
        return "TREND"
    elif mean_wr > 0.29:
        return "SIDEWAY"
    else:
        return "CHAOS"

# ================= ENGINE =================
engine = []
total_profit = 0
last_trade_round = -999
wr_history = []

next_signal = None
next_window = None
next_wr = None
next_ev = None
regime = "WARMUP"

for i, n in enumerate(numbers):
    g = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"
    window_used = None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted = next_signal
        window_used = next_window
        hit = 1 if predicted == g else 0

        if hit:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS

        wr_history.append(hit)
        state = "TRADE"
        last_trade_round = i
        next_signal = None

    # ===== DETECT REGIME =====
    regime = detect_regime(wr_history)

    # ===== GAP THEO REGIME =====
    if regime == "TREND":
        GAP = BASE_GAP
    elif regime == "SIDEWAY":
        GAP = BASE_GAP + 2
    else:  # CHAOS
        GAP = 999  # ngừng bet

    # ===== GENERATE SIGNAL =====
    if len(engine) >= MIN_SAMPLE and i - last_trade_round > GAP:

        best_window = None
        best_ev = -999
        best_wr = 0

        for w in WINDOW_RANGE:
            recent_hits = []
            start = max(w, len(engine) - LIVE_LOOKBACK)

            for j in range(start, len(engine)):
                if j >= w:
                    recent_hits.append(
                        1 if engine[j]["group"] == engine[j - w]["group"] else 0
                    )

            if len(recent_hits) >= MIN_SAMPLE:
                wr = np.mean(recent_hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                if ev > best_ev:
                    best_ev = ev
                    best_window = w
                    best_wr = wr

        # ===== CONFIRM =====
        if best_window is not None and best_wr > 0.30 and best_ev > 0:
            g1 = engine[-best_window]["group"]

            if engine[-1]["group"] != g1:
                next_signal = g1
                next_window = best_window
                next_wr = best_wr
                next_ev = best_ev
                state = "SIGNAL"

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "state": state
    })

# ================= DASHBOARD =================
st.title("🧠 LIVE REGIME AI — ADAPTIVE ENGINE")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Rounds", len(engine))
col2.metric("Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
col3.metric("Winrate %", round(wr*100,2))
col4.metric("Market Regime", regime)

# ================= NEXT SIGNAL =================
if next_signal:
    st.success(f"🎯 NEXT GROUP: {next_signal} | Window: {next_window} | WR: {round(next_wr*100,2)}%")
else:
    st.info("No valid signal")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
