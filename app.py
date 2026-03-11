import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]   # 2 window mạnh nhất

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

# ================= ADAPTIVE CORE =================
def calc_short_wr(engine, span=18):
    hits = [x["hit"] for x in engine[-span:] if x["hit"] is not None]
    return np.mean(hits) if hits else 0.5

def adaptive_lookback(short_wr):
    if short_wr >= 0.38:
        return 18   # thị trường rõ nhịp → bám sát
    elif short_wr >= 0.32:
        return 22
    else:
        return 28   # nhiễu → nhìn dài hơn

def adaptive_gap(ev):
    if ev is None:
        return 3
    if ev >= 0.40:
        return 1    # tín hiệu mạnh → vào nhanh
    elif ev >= 0.20:
        return 2
    else:
        return 4    # yếu → giãn lệnh

# ================= ENGINE =================
def run_engine():
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
        window_used = None
        wr_used = None
        ev_used = None

        # ===== EXECUTE TRADE =====
        if next_signal is not None:
            predicted = next_signal
            window_used = next_window
            wr_used = next_wr
            ev_used = next_ev

            hit = 1 if predicted == g else 0
            total_profit += WIN_PROFIT if hit else -LOSE_LOSS

            state = "TRADE"
            last_trade_round = i
            next_signal = None

        # ===== ADAPTIVE MARKET READ =====
        short_wr = calc_short_wr(engine)
        LOOKBACK = adaptive_lookback(short_wr)

        # ===== GENERATE SIGNAL =====
        if len(engine) >= 40:
            best_window = None
            best_ev = -999
            best_wr = 0

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

            GAP = adaptive_gap(best_ev)

            # ===== CONFIRM SIGNAL =====
            if (
                best_window is not None
                and best_wr > 0.29
                and best_ev > 0
                and i - last_trade_round > GAP
            ):
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
            "wr": None if wr_used is None else round(wr_used * 100, 2),
            "ev": None if ev_used is None else round(ev_used, 3),
            "state": state,
            "profit": round(total_profit, 2)
        })

    return total_profit, engine, next_signal, next_window, next_wr, next_ev

# ================= RUN =================
profit, engine, next_signal, next_window, next_wr, next_ev = run_engine()

# ================= DASHBOARD =================
st.title("⚡ TURBO ADAPTIVE PRO — LIVE")

c1, c2, c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Profit", round(profit, 2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr * 100, 2))

st.caption("Adaptive Lookback + Adaptive Gap | Windows=[9,15]")

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
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)
