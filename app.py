import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOW = 9

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
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    return df

df = load()
if df.empty or "number" not in df.columns:
    st.error("Data lỗi hoặc thiếu cột 'number'")
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= TURBO PARAM ADAPT =================
def turbo_params(engine):
    recent_hits = [x["hit"] for x in engine[-12:] if x["hit"] is not None]
    if len(recent_hits) < 6:
        return 22, 2, "WARMUP"

    wr = np.mean(recent_hits)

    if wr >= 0.58:
        return 18, 1, "🚀 TURBO"
    elif wr >= 0.48:
        return 22, 2, "⚖️ NORMAL"
    else:
        return 28, 4, "🧊 SAFE"

# ================= ENGINE =================
def run_engine():
    engine = []
    total_profit = 0
    peak_profit = 0
    last_trade_round = -999

    next_signal = None
    mode = "WARMUP"
    LB, GAP = 22, 2

    for i, n in enumerate(numbers):
        g = get_group(n)

        predicted = None
        hit = None
        state = "SCAN"
        wr_view = None
        ev_view = None

        # ===== EXECUTE =====
        if next_signal is not None:
            predicted = next_signal
            hit = 1 if predicted == g else 0
            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += pnl
            peak_profit = max(peak_profit, total_profit)

            state = "TRADE"
            last_trade_round = i
            next_signal = None

        # ===== ADAPT TURBO =====
        if len(engine) > 20:
            LB, GAP, mode = turbo_params(engine)

        # ===== SIGNAL =====
        if len(engine) >= 40 and i - last_trade_round > GAP:
            recent_hits = []
            start = max(WINDOW, len(engine) - LB)

            for j in range(start, len(engine)):
                if j >= WINDOW:
                    recent_hits.append(
                        1 if engine[j]["group"] == engine[j - WINDOW]["group"] else 0
                    )

            if len(recent_hits) >= 12:
                wr = np.mean(recent_hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                # Turbo entry (nới điều kiện)
                if wr > 0.24 and ev > -0.05:
                    g1 = engine[-WINDOW]["group"]
                    if engine[-1]["group"] != g1:
                        next_signal = g1
                        state = "SIGNAL"
                        wr_view = round(wr * 100, 2)
                        ev_view = round(ev, 3)

        dd = peak_profit - total_profit

        engine.append({
            "round": i + 1,
            "number": n,
            "group": g,
            "predicted": predicted,
            "hit": hit,
            "state": state,
            "profit": round(total_profit,2),
            "peak": round(peak_profit,2),
            "dd": round(dd,2),
            "lookback": LB,
            "gap": GAP,
            "mode": mode,
            "wr": wr_view,
            "ev": ev_view
        })

    return engine, next_signal, mode

engine, next_signal, mode = run_engine()

# ================= DASHBOARD =================
st.title("🚀 TURBO TREND ENGINE")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Profit", engine[-1]["profit"])
hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr*100,2))

st.caption(f"Window=9 | Turbo Adaptive | Mode: {mode}")

# ================= SIGNAL =================
if next_signal:
    st.error(f"🚨 NEXT GROUP: {next_signal}")
else:
    st.info("Scanning...")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
