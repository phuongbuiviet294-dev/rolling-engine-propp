import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 14]

st.set_page_config(layout="wide")

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

@st.cache_data(ttl=5)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
numbers = df["number"].dropna().astype(int).tolist()

engine = []
total_profit = 0
last_trade_round = -999
next_signal = None

for i, n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    regime_label = None
    window_used = None
    ev_value = None
    wr_value = None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted = next_signal
        hit = 1 if predicted == g else 0
        if hit:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS
        state = "TRADE"
        last_trade_round = i
        next_signal = None

    # ===== REGIME DETECTION =====
    if len(engine) > 150:

        short_hits = []
        long_hits = []

        for j in range(len(engine)-30, len(engine)):
            for w in WINDOWS:
                if j >= w:
                    short_hits.append(
                        1 if engine[j]["group"] == engine[j-w]["group"] else 0
                    )

        for j in range(len(engine)-120, len(engine)):
            for w in WINDOWS:
                if j >= w:
                    long_hits.append(
                        1 if engine[j]["group"] == engine[j-w]["group"] else 0
                    )

        short_wr = np.mean(short_hits) if short_hits else 0
        long_wr = np.mean(long_hits) if long_hits else 0
        deviation = short_wr - long_wr

        if short_wr >= 0.38:
            regime_label = "🔥 STRONG"
            cooldown = 6
            wr_threshold = 0.31
        elif deviation >= 0.05:
            regime_label = "⚡ SHIFT"
            cooldown = 8
            wr_threshold = 0.31
        elif short_wr >= 0.32:
            regime_label = "🧊 STABLE"
            cooldown = 10
            wr_threshold = 0.32
        else:
            regime_label = "❌ RANDOM"
            cooldown = 999
            wr_threshold = 1

        # ===== DOMINANCE CHECK =====
        recent_groups = [x["group"] for x in engine[-60:]]
        counts = pd.Series(recent_groups).value_counts(normalize=True)

        dominant_group = None
        if not counts.empty and counts.max() >= 0.38:
            dominant_group = counts.idxmax()

        # ===== WINDOW CHECK =====
        best_window = None
        best_wr = 0
        best_ev = -999

        for w in WINDOWS:
            hits = []
            for j in range(len(engine)-40, len(engine)):
                if j >= w:
                    hits.append(
                        1 if engine[j]["group"] == engine[j-w]["group"] else 0
                    )
            if len(hits) >= 25:
                wr = np.mean(hits)
                ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS
                if ev > best_ev:
                    best_ev = ev
                    best_wr = wr
                    best_window = w

        # ===== TRADE CONDITION =====
        if i - last_trade_round > cooldown:

            if dominant_group is not None:
                next_signal = dominant_group
                state = "DOMINANCE SIGNAL"

            elif best_window is not None and \
                 best_wr >= wr_threshold and \
                 best_ev >= 0.15:

                next_signal = engine[-best_window]["group"]
                state = "WINDOW SIGNAL"
                window_used = best_window
                wr_value = round(best_wr*100,2)
                ev_value = round(best_ev,3)

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state,
        "regime": regime_label,
        "window": window_used,
        "wr": wr_value,
        "ev": ev_value
    })

# ================= DASHBOARD =================

st.title("🔥 FINAL REGIME + DOMINANCE ENGINE")

col1, col2, col3 = st.columns(3)
col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr_final = np.mean(hits)*100 if hits else 0
col3.metric("Winrate %", round(wr_final,2))

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
        🚨 NEXT GROUP: {next_signal}
    </div>
    """, unsafe_allow_html=True)

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)
