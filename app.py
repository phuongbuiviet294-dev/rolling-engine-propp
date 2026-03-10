
import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9,13]

st.set_page_config(layout="wide")


# ================= GROUP ================= #

def get_group(n):

    if 1 <= n <= 3:
        return 1
    if 4 <= n <= 6:
        return 2
    if 7 <= n <= 9:
        return 3
    if 10 <= n <= 12:
        return 4
    return None


# ================= LOAD ================= #

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


for i, n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    window_used = None
    rolling_wr = None
    ev_value = None
    reason = None


    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal
        window_used = next_window
        rolling_wr = next_wr
        ev_value = next_ev

        hit = 1 if predicted == g else 0

        if hit == 1:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS

        state = "TRADE"

        reason = f"Executed signal from round {signal_created_at}"

        last_trade_round = i

        next_signal = None


    # ===== GENERATE SIGNAL =====

    if len(engine) >= 40 and i - last_trade_round > 4:

        best_window = None
        best_ev = -999
        best_wr = 0

        for w in WINDOWS:

            recent_hits = []

            start = max(w, len(engine)-26)

            for j in range(start, len(engine)):

                if j >= w:

                    recent_hits.append(
                        1 if engine[j]["group"] == engine[j-w]["group"] else 0
                    )

            if len(recent_hits) >= 20:

                wr = np.mean(recent_hits)

                ev = wr * WIN_PROFIT - (1-wr)*LOSE_LOSS

                if ev > best_ev:

                    best_ev = ev
                    best_window = w
                    best_wr = wr


        # ===== PREVIEW =====

        if best_window is not None and best_wr > 0.28:

            preview_signal = engine[-best_window]["group"]
            preview_window = best_window
            preview_wr = round(best_wr*100,2)
            preview_ev = round(best_ev,3)


        # ===== CONFIRM TRADE =====

        if best_window is not None:

            if best_wr > 0.29 and best_ev > -0.01:

                g1 = engine[-best_window]["group"]

                # timing filter
                if engine[-1]["group"] != g1:

                    next_signal = g1

                    next_window = best_window
                    next_wr = round(best_wr*100,2)
                    next_ev = round(best_ev,3)

                    signal_created_at = i + 1

                    state = "SIGNAL"

                    reason = f"Window {best_window}"


    engine.append({

        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "rolling_wr_%": rolling_wr,
        "ev": ev_value,
        "state": state,
        "reason": reason

    })


# ================= DASHBOARD ================= #

st.title("🎯 FINAL CLEAN ONE-SHOT ENGINE")


col1, col2, col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))

col2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr = np.mean(hits)

    col3.metric("Winrate %", round(wr*100,2))

else:

    col3.metric("Winrate %",0)


# ================= PREVIEW ================= #

if preview_signal is not None:

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

    </div>
    """, unsafe_allow_html=True)


# ================= NEXT GROUP ================= #

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

        <br>WR: {next_wr}%

        <br>EV: {next_ev}

    </div>
    """, unsafe_allow_html=True)

else:

    st.info("No valid signal yet")


# ================= HISTORY ================= #

st.subheader("History")

hist_df = pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df, use_container_width=True)

st.caption("WINDOW 9 & 14 | EV FILTER | TIMING ENTRY")
