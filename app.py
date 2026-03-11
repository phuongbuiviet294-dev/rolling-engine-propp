import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))   # ✅ chạy full window theo thị trường
LOOKBACK = 26                 # nhìn gần
GAP = 2                       # turbo vào nhanh

RECENT_TRADE_WINDOW = 12      # đo trend gần
MIN_SAMPLES = 30

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
def run_engine():
    engine = []
    total_profit = 0
    last_trade_round = -999

    next_signal = None
    next_window = None
    next_ev = None
    next_wr = None

    trade_profits = []

    for i, n in enumerate(numbers):
        g = get_group(n)

        predicted=None; hit=None; state="SCAN"
        window_used=None; ev_value=None; wr_value=None

        # ===== EXECUTE =====
        if next_signal is not None:
            predicted = next_signal
            window_used = next_window
            ev_value = next_ev
            wr_value = next_wr

            hit = 1 if predicted == g else 0
            profit_change = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += profit_change
            trade_profits.append(profit_change)

            state="TRADE"
            last_trade_round = i
            next_signal=None

        # ===== CALC RECENT PROFIT =====
        recent_profit = sum(trade_profits[-RECENT_TRADE_WINDOW:]) if trade_profits else 0

        # ===== GENERATE =====
        if len(engine) >= MIN_SAMPLES and i - last_trade_round > GAP:

            best_window=None
            best_score=-999
            best_ev=None
            best_wr=None

            for w in WINDOWS:
                hits=[]
                start=max(w, len(engine)-LOOKBACK)

                for j in range(start, len(engine)):
                    if j>=w:
                        hits.append(
                            1 if engine[j]["group"] == engine[j-w]["group"] else 0
                        )

                if len(hits) >= 20:
                    wr = np.mean(hits)
                    ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS

                    # ✅ TURBO TREND LOGIC
                    # EV dương + profit gần đây dương => theo trend
                    if ev > 0 and recent_profit > 0:
                        trend_score = ev*0.7 + recent_profit*0.3
                        if trend_score > best_score:
                            best_score = trend_score
                            best_window = w
                            best_ev = ev
                            best_wr = wr

            if best_window is not None:
                g1 = engine[-best_window]["group"]
                if engine[-1]["group"] != g1:
                    next_signal = g1
                    next_window = best_window
                    next_ev = best_ev
                    next_wr = best_wr
                    state="SIGNAL"

        engine.append({
            "round": i+1,
            "number": n,
            "group": g,
            "predicted": predicted,
            "hit": hit,
            "window": window_used,
            "wr": None if wr_value is None else round(wr_value*100,2),
            "ev": None if ev_value is None else round(ev_value,3),
            "recent_profit": round(recent_profit,2),
            "state": state,
            "total_profit": round(total_profit,2)
        })

    return total_profit, engine, next_signal, next_window, next_wr, next_ev


# ================= RUN =================
profit, engine, next_signal, next_window, next_wr, next_ev = run_engine()

# ================= UI =================
st.title("⚡ TURBO TREND PRO")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Total Profit", round(profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr*100,2))

st.caption(f"Trend Mode | Windows=8→18 | Lookback={LOOKBACK} | Gap={GAP}")

# ================= SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;
                font-size:28px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {round(next_wr*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning trend...")

# ================= HISTORY =================
st.subheader("Live History (No Repaint)")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
