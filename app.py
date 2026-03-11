import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]

BASE_LOOKBACK = 26
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
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

df = load()
if df.empty or "number" not in df.columns:
    st.error("Data lỗi hoặc thiếu cột 'number'")
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= AUTO ADAPT =================
def adapt_params(engine):
    recent_hits = [x["hit"] for x in engine[-25:] if x["hit"] is not None]

    # ===== Adapt theo HIT =====
    if len(recent_hits) >= 5:
        wr = np.mean(recent_hits)

        if wr > 0.55:
            return 22, 2   # trend mạnh → vào nhanh
        elif wr > 0.48:
            return 26, 3   # ổn định
        else:
            return 32, 5   # xấu → giãn lệnh

    # ===== Adapt theo PROFIT FLOW =====
    if len(engine) >= 20:
        p0 = engine[-20]["total_profit"]
        p1 = engine[-1]["total_profit"]
        slope = p1 - p0

        if slope > 5:
            return 22, 2
        elif slope > 0:
            return 26, 3
        else:
            return 32, 5

    return BASE_LOOKBACK, BASE_GAP

# ================= ENGINE =================
def run_live_engine():
    engine = []
    total_profit = 0
    last_trade_round = -999

    next_signal = None
    next_window = None
    next_wr = None
    next_ev = None

    sticky_window = None
    sticky_loss = 0

    LB = BASE_LOOKBACK
    GP = BASE_GAP

    for i, n in enumerate(numbers):
        g = get_group(n)

        predicted = None
        hit = None
        state = "SCAN"
        window_used = None
        rolling_wr = None
        ev_value = None

        # ===== EXECUTE TRADE =====
        if next_signal is not None:
            predicted = next_signal
            window_used = next_window
            rolling_wr = next_wr
            ev_value = next_ev

            hit = 1 if predicted == g else 0
            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += pnl

            state = "TRADE"
            last_trade_round = i
            next_signal = None

            # Sticky logic
            if hit:
                sticky_window = window_used
                sticky_loss = 0
            else:
                sticky_loss += 1
                if sticky_loss >= 3:
                    sticky_window = None

        # ===== ADAPT PARAMS REALTIME =====
        if len(engine) > 30:
            LB, GP = adapt_params(engine)

        # ===== GENERATE SIGNAL =====
        if len(engine) >= 40 and i - last_trade_round > GP:
            best_window = None
            best_ev = -999
            best_wr = 0

            candidate_windows = [sticky_window] if sticky_window else WINDOWS

            for w in candidate_windows:
                if w is None:
                    continue

                recent_hits = []
                start = max(w, len(engine) - LB)

                for j in range(start, len(engine)):
                    if j >= w:
                        recent_hits.append(
                            1 if engine[j]["group"] == engine[j - w]["group"] else 0
                        )

                if len(recent_hits) >= 12:
                    wr = np.mean(recent_hits)
                    ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                    if ev > best_ev:
                        best_ev = ev
                        best_window = w
                        best_wr = wr

            # ===== SOFT ENTRY (không scan vô hạn) =====
            if best_window is not None and best_wr > 0.27:
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
            "wr": None if rolling_wr is None else round(rolling_wr * 100, 2),
            "ev": None if ev_value is None else round(ev_value, 3),
            "state": state,
            "total_profit": round(total_profit, 2),
            "lookback": LB,
            "gap": GP
        })

    return engine, next_signal, next_window, next_wr, next_ev

# ================= RUN =================
engine, next_signal, next_window, next_wr, next_ev = run_live_engine()

# ================= DASHBOARD =================
st.title("🚀 LIVE BETTING ENGINE — AUTO ADAPT FIXED")

c1, c2, c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Profit", engine[-1]["total_profit"])

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr * 100, 2))

st.caption(f"Windows={WINDOWS} | Sticky Window ON | Auto Lookback & Gap")

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
        🚨 READY TO BET 🚨<br>
        🎯 NEXT GROUP: {next_signal}<br>
        Window: {next_window}<br>
        WR: {round(next_wr*100,2)}%<br>
        EV: {round(next_ev,3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
