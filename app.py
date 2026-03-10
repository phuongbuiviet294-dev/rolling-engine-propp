import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9]

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

    loss_streak = 0  # 🔹 PROTECT

    for i, n in enumerate(numbers):
        g = get_group(n)
        predicted = None
        hit = None
        state = "SCAN"
        window_used = None
        rolling_wr = None
        ev_value = None

        # ===== EXECUTE =====
        if next_signal is not None:
            predicted = next_signal
            window_used = next_window
            rolling_wr = next_wr
            ev_value = next_ev

            hit = 1 if predicted == g else 0

            if hit == 1:
                total_profit += WIN_PROFIT
                loss_streak = 0
            else:
                total_profit -= LOSE_LOSS
                loss_streak += 1

            state = "TRADE"
            last_trade_round = i
            next_signal = None

        # ===== GENERATE =====
        if len(engine) >= 40 and i - last_trade_round > GAP:
            best_window = None
            best_ev = -999
            best_wr = 0
            best_hits = []

            for w in WINDOWS:
                recent_hits = []
                start = max(w, len(engine) - LOOKBACK)

                for j in range(start, len(engine)):
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
                        best_hits = recent_hits

            # ===== PRO SHIELD FILTERS =====
            if best_window is not None:
                short_wr = np.mean(best_hits[-10:]) if len(best_hits) >= 10 else 0
                g1 = engine[-best_window]["group"]

                # anti repeat filter
                recent_groups = [engine[-k]["group"] for k in range(1, min(6, len(engine)))]
                repeat_ok = recent_groups.count(g1) <= 2

                if (
                    best_wr > 0.29
                    and best_ev > 0
                    and short_wr > 0.35      # 🔹 short-term strength
                    and loss_streak < 2     # 🔹 anti losing streak
                    and repeat_ok           # 🔹 anti noise
                ):
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
            "wr": None if rolling_wr is None else round(rolling_wr*100,2),
            "ev": None if ev_value is None else round(ev_value,3),
            "loss_streak": loss_streak,
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

# ================= DASHBOARD =================
st.title("🛡️ PRO SHIELD BETTING ENGINE")

col1, col2, col3 = st.columns(3)
col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(best_profit, 2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
col3.metric("Winrate %", round(wr * 100, 2))

st.caption(f"Optimized | Lookback={LOOKBACK} | Gap={GAP}")

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
    st.info("No valid signal yet")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
