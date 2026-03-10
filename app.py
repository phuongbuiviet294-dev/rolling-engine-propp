import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]

RECENT_TRAIN = 300
EQUITY_PROTECT_ROUNDS = 50
REGIME_FILTER_ROUNDS = 20

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
def run_engine(LOOKBACK, GAP):
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

        # ===== EXECUTE =====
        if next_signal is not None:
            predicted = next_signal
            hit = 1 if predicted == g else 0

            total_profit += WIN_PROFIT if hit else -LOSE_LOSS
            state = "TRADE"
            last_trade_round = i
            next_signal = None

        # ===== PROTECTION LAYERS =====
        allow_trade = True

        # Equity Protection
        recent_hits = [x["hit"] for x in engine[-EQUITY_PROTECT_ROUNDS:] if x["hit"] is not None]
        if len(recent_hits) >= 20:
            recent_profit = sum([WIN_PROFIT if h==1 else -LOSE_LOSS for h in recent_hits])
            if recent_profit <= 0:
                allow_trade = False

        # Regime Filter
        recent_evs = [x["ev"] for x in engine[-REGIME_FILTER_ROUNDS:] if x["ev"] is not None]
        if len(recent_evs) >= 10:
            if np.mean(recent_evs) <= 0:
                allow_trade = False

        # ===== GENERATE =====
        if allow_trade and len(engine) >= 40 and i - last_trade_round > GAP:
            best_window = None
            best_ev = -999
            best_wr = 0

            start_base = max(0, len(engine) - RECENT_TRAIN)

            for w in WINDOWS:
                recent_hits = []
                start = max(w, len(engine) - LOOKBACK)

                for j in range(max(start, start_base), len(engine)):
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

            if best_window is not None and best_wr > 0.29 and best_ev > 0:
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
            "ev": next_ev if state=="TRADE" else None,
            "state": state
        })

    return total_profit, engine, next_signal, next_window, next_wr, next_ev

# ================= AUTO OPT =================
best_profit = -999
best_cfg = None
best_engine = None
best_next = None

for LOOKBACK in range(20, 41):
    for GAP in range(3, 7):
        profit, eng, ns, nw, nwr, nev = run_engine(LOOKBACK, GAP)
        if profit > best_profit:
            best_profit = profit
            best_cfg = (LOOKBACK, GAP)
            best_engine = eng
            best_next = (ns, nw, nwr, nev)

LOOKBACK, GAP = best_cfg
engine = best_engine
next_signal, next_window, next_wr, next_ev = best_next

# ================= UI =================
st.title("🧠 AI BETTING ENGINE — PROTECT PROFIT MODE")

col1, col2, col3 = st.columns(3)
col1.metric("Rounds", len(engine))
col2.metric("Profit", round(best_profit,2))
hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
col3.metric("Winrate %", round(wr*100,2))

st.caption(f"Adaptive Mode | Lookback={LOOKBACK} | Gap={GAP}")

if next_signal is not None:
    st.success(f"🎯 NEXT GROUP: {next_signal} | Window={next_window} | WR={round(next_wr*100,2)}% | EV={round(next_ev,3)}")
else:
    st.info("No valid signal")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)
