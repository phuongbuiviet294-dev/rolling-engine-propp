import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 14]

st.set_page_config(layout="wide")

# ================= CORE ================= #

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE ================= #

engine = []
total_profit = 0
last_trade_round = -999

next_signal = None
next_window = None
next_wr = None
next_ev = None
signal_created_at = None

preview_signal = None
preview_window = None
preview_wr = None
preview_ev = None

current_mode = "STABILITY"

for i, n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    reason = None

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

    # ===== HYBRID LOGIC =====
    if len(engine) >= 150:

        # ---- SHORT / LONG WR ----
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

        if short_hits and long_hits:

            short_wr = np.mean(short_hits)
            long_wr = np.mean(long_hits)
            deviation = short_wr - long_wr

            # ---- MODE SWITCH ----
            if short_wr >= 0.42:
                current_mode = "AGGRESSIVE"
                wr_threshold = 0.30
                cooldown = 6
            elif deviation >= 0.04:
                current_mode = "PROFIT"
                wr_threshold = 0.30
                cooldown = 10
            else:
                current_mode = "STABILITY"
                wr_threshold = 0.31
                cooldown = 12

            # ---- SIGNAL ----
            if i - last_trade_round > cooldown:

                window_stats = []

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
                        window_stats.append((w, wr, ev))

                if len(window_stats) == 2:

                    window_stats.sort(key=lambda x: x[1], reverse=True)

                    best_w, best_wr, best_ev = window_stats[0]
                    second_wr = window_stats[1][1]

                    # ---- PREVIEW ----
                    if best_wr >= 0.29:
                        preview_signal = engine[-best_w]["group"]
                        preview_window = best_w
                        preview_wr = round(best_wr*100,2)
                        preview_ev = round(best_ev,3)

                    # ---- CONFIRM TRADE ----
                    if (best_wr - second_wr) >= 0.05 and \
                       best_wr >= wr_threshold and \
                       best_ev >= 0:

                        next_signal = engine[-best_w]["group"]
                        next_window = best_w
                        next_wr = round(best_wr*100,2)
                        next_ev = round(best_ev,3)
                        signal_created_at = i+1
                        state = "SIGNAL"
                        reason = f"{current_mode} regime detected"

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state,
        "mode": current_mode,
        "reason": reason
    })

# ================= DASHBOARD ================= #

st.title("🔥 HYBRID ONE-SHOT ENGINE")

col1, col2, col3 = st.columns(3)
col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
if hits:
    col3.metric("Winrate %", round(np.mean(hits)*100,2))
else:
    col3.metric("Winrate %", 0)

# ================= PREVIEW ================= #

if preview_signal:
    st.markdown(f"""
    <div style='padding:15px;
                background:#444;
                color:white;
                border-radius:10px;
                text-align:center;
                font-size:20px'>
        🔎 PREVIEW SIGNAL: {preview_signal}
        <br>Window: {preview_window}
        <br>WR: {preview_wr}%
        <br>EV: {preview_ev}
        <br>Mode: {current_mode}
    </div>
    """, unsafe_allow_html=True)

# ================= NEXT GROUP ================= #

if next_signal:
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
        <br>WR: {next_wr}%
        <br>EV: {next_ev}
        <br>MODE: {current_mode}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("No strong regime detected")

# ================= HISTORY ================= #

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)

st.caption("HYBRID REGIME | Dominant Window | Deviation Filter | Dynamic Cooldown")
