import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,14]

# ===== SEARCH SPACE =====
LOOKBACKS = range(20, 35)        # bạn thấy -26 tốt → quét rộng quanh đó
COOLDOWNS = range(1, 6)          # 1→5
EV_THRESHOLDS = [ -0.01, 0, 0.03, 0.05, 0.08 ]

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

# ================= BACKTEST CORE =================
def run_engine(lookback, cooldown, ev_threshold):
    engine = []
    total_profit = 0
    last_trade_round = -999

    next_signal = None
    next_window = None
    next_ev = None

    for i, n in enumerate(numbers):
        g = get_group(n)

        # ===== EXECUTE =====
        if next_signal is not None:
            hit = 1 if next_signal == g else 0
            if hit:
                total_profit += WIN_PROFIT
            else:
                total_profit -= LOSE_LOSS

            last_trade_round = i
            next_signal = None

        # ===== GENERATE =====
        if len(engine) >= 40 and i - last_trade_round > cooldown:
            best_window = None
            best_ev = -999
            best_wr = 0

            for w in WINDOWS:
                recent_hits = []
                start = max(w, len(engine) - lookback)

                for j in range(start, len(engine)):
                    if j >= w:
                        recent_hits.append(
                            1 if engine[j]["group"] == engine[j-w]["group"] else 0
                        )

                if len(recent_hits) >= 20:
                    wr = np.mean(recent_hits)
                    ev = wr * WIN_PROFIT - (1-wr)*LOSE_LOSS
                    if ev > best_ev:
                        best_ev = ev
                        best_window = w
                        best_wr = wr

            if best_window is not None and best_ev > ev_threshold:
                next_signal = engine[-best_window]["group"]
                next_window = best_window
                next_ev = best_ev

        engine.append({"group": g})

    return total_profit

# ================= AUTO OPTIMIZER =================
best_profit = -9999
best_params = None

with st.spinner("🔍 Auto-optimizing parameters..."):
    for lb in LOOKBACKS:
        for cd in COOLDOWNS:
            for ev_th in EV_THRESHOLDS:
                profit = run_engine(lb, cd, ev_th)
                if profit > best_profit:
                    best_profit = profit
                    best_params = (lb, cd, ev_th)

LOOKBACK_OPT, COOLDOWN_OPT, EV_TH_OPT = best_params

# ================= DASHBOARD =================
st.title("🤖 AUTO OPTIMIZER — MAX PROFIT ENGINE")

c1,c2,c3 = st.columns(3)
c1.metric("Best Profit", round(best_profit,2))
c2.metric("Lookback", LOOKBACK_OPT)
c3.metric("Cooldown", COOLDOWN_OPT)

st.metric("EV Threshold", EV_TH_OPT)

st.success("Parameters auto-selected for maximum profit")
