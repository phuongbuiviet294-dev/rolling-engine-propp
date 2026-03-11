import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9, 15]

# ---- Cycle Scan Config (QUAN TRỌNG) ----
LOOKBACK_RANGE = range(18, 29)   # bắt trend ngắn hạn
GAP_RANGE = range(2, 5)          # không bỏ nhịp
MIN_WR = 0.30                    # winrate tối thiểu
MIN_EV = 0.05                    # edge tối thiểu
MIN_SAMPLE = 12                  # số mẫu tối thiểu

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

# ================= AUTO CYCLE OPTIMIZER =================
def find_best_cycle(engine):
    best_score = -999
    best_lb = 26
    best_gp = 3

    for LB in LOOKBACK_RANGE:
        for GP in GAP_RANGE:
            profit = 0
            last_trade = -999
            trades = 0

            for i in range(len(engine)):
                if i - last_trade <= GP:
                    continue

                best_ev = -999

                for w in WINDOWS:
                    hits = []
                    start = max(w, i - LB)

                    for j in range(start, i):
                        if j >= w:
                            hits.append(
                                1 if engine[j]["group"] == engine[j-w]["group"] else 0
                            )

                    if len(hits) >= MIN_SAMPLE:
                        wr = np.mean(hits)
                        ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS
                        if wr >= MIN_WR and ev >= MIN_EV and ev > best_ev:
                            best_ev = ev

                if best_ev > 0:
                    profit += best_ev
                    trades += 1
                    last_trade = i

            score = profit * 0.7 + trades * 0.3
            if score > best_score:
                best_score = score
                best_lb = LB
                best_gp = GP

    return best_lb, best_gp

# ================= LIVE ENGINE =================
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

    LB = 26
    GP = 3

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

            if hit:
                sticky_window = window_used
                sticky_loss = 0
            else:
                sticky_loss += 1
                if sticky_loss >= 3:
                    sticky_window = None

        # ===== AUTO OPTIMIZE CYCLE =====
        if len(engine) > 60 and i % 20 == 0:
            LB, GP = find_best_cycle(engine)

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

                if len(recent_hits) >= MIN_SAMPLE:
                    wr = np.mean(recent_hits)
                    ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                    if wr >= MIN_WR and ev >= MIN_EV and ev > best_ev:
                        best_ev = ev
                        best_window = w
                        best_wr = wr

            if best_window is not None:
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

    return engine, total_profit, next_signal, next_window, next_wr, next_ev

# ================= RUN =================
engine, total_profit, next_signal, next_window, next_wr, next_ev = run_live_engine()

# ================= DASHBOARD =================
st.title("🚀 AUTO CYCLE TREND ENGINE")

c1, c2, c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Profit", total_profit)

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr * 100, 2))

st.caption(f"Windows={WINDOWS} | Auto Cycle ON | Sticky Window ON")

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
