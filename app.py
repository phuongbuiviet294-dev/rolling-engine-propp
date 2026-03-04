import streamlit as st
import pandas as pd
import numpy as np
import math
from collections import Counter

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(4,31)

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

numbers = df["number"].dropna().astype(int).tolist()

engine = []

total_profit = 0
last_trade_round = -999

next_signal = None
next_window = None
next_wr = None
next_ev = None

preview_signal = None
preview_window = None
preview_wr = None
preview_ev = None

retry_mode = False

# ================= ENGINE ================= #

for i,n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"

# ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal

        hit = 1 if predicted == g else 0

        if hit:

            total_profit += WIN_PROFIT
            retry_mode = False
            next_signal = None

        else:

            total_profit -= LOSE_LOSS

            if retry_mode == False:
                retry_mode = True
            else:
                retry_mode = False
                next_signal = None

        state = "TRADE"
        last_trade_round = i

# ===== AI WINDOW SEARCH =====

    if len(engine) >= 40 and next_signal is None:

        best_score = -999
        best_window = None
        best_wr = 0
        best_ev = 0

        for w in WINDOW_RANGE:

            hits = []

            for j in range(len(engine)-25, len(engine)):

                if j >= w:

                    if engine[j]["group"] == engine[j-w]["group"]:
                        hits.append(1)
                    else:
                        hits.append(0)

            if len(hits) < 15:
                continue

            wr = np.mean(hits)

            ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS

            stability = 1 - np.var(hits)

            score = ev * stability * math.log(len(hits))

            if score > best_score:

                best_score = score
                best_window = w
                best_wr = wr
                best_ev = ev

# ===== REGIME FILTER (only after 150 rounds) =====

        recent_hits = [x["hit"] for x in engine[-20:] if x["hit"] is not None]

        regime_wr = 0

        if recent_hits:
            regime_wr = np.mean(recent_hits)

        if len(engine) > 150 and regime_wr < 0.27:
            continue

# ===== DOMINANCE FILTER =====

        recent_groups = [x["group"] for x in engine[-20:]]

        freq = Counter(recent_groups)

        dominant = max(freq, key=freq.get)

# ===== PREVIEW =====

        if best_window and best_wr > 0.30:

            preview_signal = engine[-best_window]["group"]
            preview_window = best_window
            preview_wr = round(best_wr*100,2)
            preview_ev = round(best_ev,3)

# ===== ADAPTIVE COOLDOWN =====

        cooldown = 6

        if best_wr >= 0.36:
            cooldown = 2
        elif best_wr >= 0.33:
            cooldown = 3
        elif best_wr >= 0.30:
            cooldown = 4

# ===== CONFIRM TRADE =====

        if best_window and best_wr > 0.32 and best_ev > 0:

            signal_group = engine[-best_window]["group"]

            if signal_group == dominant and i-last_trade_round > cooldown:

                next_signal = signal_group
                next_window = best_window
                next_wr = round(best_wr*100,2)
                next_ev = round(best_ev,3)

                state = "SIGNAL"

# ===== SAVE ENGINE =====

    engine.append({

        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": next_window,
        "state": state

    })

# ================= DASHBOARD ================= #

st.title("⚡ QUANT ADAPTIVE ENGINE (FIXED)")

col1,col2,col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr = np.mean(hits)
    col3.metric("Winrate %", round(wr*100,2))

# ===== PREVIEW =====

if preview_signal:

    st.markdown(f"""
<div style='padding:15px;background:#444;color:white;border-radius:10px;text-align:center;font-size:20px'>

🔎 PREVIEW SIGNAL: {preview_signal}

Window: {preview_window}

WR: {preview_wr} %

EV: {preview_ev}

</div>
""",unsafe_allow_html=True)

# ===== NEXT GROUP =====

if next_signal:

    st.markdown(f"""
<div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:28px;font-weight:bold'>

🚨 READY TO BET 🚨

NEXT GROUP: {next_signal}

Window: {next_window}

WR: {next_wr} %

EV: {next_ev}

</div>
""",unsafe_allow_html=True)

else:

    st.info("No valid signal yet")

# ===== HISTORY =====

st.subheader("History")

hist_df = pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)

st.caption("QUANT ADAPTIVE ENGINE | FIXED VERSION")
