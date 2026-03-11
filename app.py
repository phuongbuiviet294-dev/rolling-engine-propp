import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9]   # scalper nên dùng window ngắn

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

# ================= TREND DETECTOR =================
def get_trend_params(engine):
    recent_hits = [x["hit"] for x in engine[-20:] if x["hit"] is not None]

    if len(recent_hits) < 10:
        return 26, 3   # mặc định

    wr = np.mean(recent_hits)

    # 🔥 Trend mạnh → đánh nhanh
    if wr >= 0.55:
        return 18, 1

    # 🙂 Trend vừa → bình thường
    elif wr >= 0.48:
        return 24, 2

    # 🧊 Trend xấu → chậm lại
    else:
        return 32, 4

# ================= ENGINE =================
def run_engine():
    engine = []
    total_profit = 0
    last_trade_round = -999

    next_signal = None
    next_wr = None
    next_ev = None

    sticky_window = None
    sticky_loss = 0

    LB, GAP = 26, 3

    for i, n in enumerate(numbers):
        g = get_group(n)

        predicted = None
        hit = None
        state = "SCAN"
        rolling_wr = None
        ev_value = None

        # ===== EXECUTE =====
        if next_signal is not None:
            predicted = next_signal
            rolling_wr = next_wr
            ev_value = next_ev

            hit = 1 if predicted == g else 0
            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += pnl

            state = "TRADE"
            last_trade_round = i
            next_signal = None

            # Sticky window logic
            if hit:
                sticky_loss = 0
            else:
                sticky_loss += 1

        # ===== UPDATE TREND PARAMS =====
        if len(engine) > 25:
            LB, GAP = get_trend_params(engine)

        # ===== GENERATE SIGNAL =====
        if len(engine) >= 30 and i - last_trade_round > GAP:
            best_ev = -999
            best_wr = 0

            for w in WINDOWS:
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
                        best_wr = wr

            # ⚡ SOFT ENTRY — scalper chỉ cần EV hơi dương
            if best_wr > 0.26 and best_ev > -0.05:
                prev_group = engine[-9]["group"]
                if engine[-1]["group"] != prev_group:
                    next_signal = prev_group
                    next_wr = best_wr
                    next_ev = best_ev
                    state = "SIGNAL"

        engine.append({
            "round": i + 1,
            "number": n,
            "group": g,
            "predicted": predicted,
            "hit": hit,
            "wr": None if rolling_wr is None else round(rolling_wr * 100, 2),
            "ev": None if ev_value is None else round(ev_value, 3),
            "state": state,
            "lookback": LB,
            "gap": GAP,
            "profit": round(total_profit, 2)
        })

    return engine, next_signal, next_wr, next_ev

# ================= RUN =================
engine, next_signal, next_wr, next_ev = run_engine()

# ================= DASHBOARD =================
st.title("⚡ SCALPER MODE — HIGH FREQUENCY")

c1, c2, c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Profit", engine[-1]["profit"])

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr * 100, 2))

st.caption("Scalper Mode | Fast Entry | Short Trend | Adaptive Speed")

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
        🚨 SCALP ENTRY 🚨<br>
        🎯 NEXT GROUP: {next_signal}<br>
        WR: {round(next_wr*100,2)}%<br>
        EV: {round(next_ev,3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning scalper setup...")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
