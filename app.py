import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(5,31)

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

groups = [get_group(x) for x in numbers]

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

signal_created_round = None

retry_mode = False

# ================= ENGINE ================= #

for i,n in enumerate(numbers):

    g = groups[i]

    predicted = None
    hit = None
    state = "SCAN"

# ===== EXECUTE TRADE =====

    if next_signal is not None and signal_created_round < i:

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

                next_signal = None
                retry_mode = False

        state = "TRADE"
        last_trade_round = i

# ===== WINDOW SCAN =====

    if len(engine) >= 50 and next_signal is None:

        best_window = None
        best_wr = 0
        best_ev = -999

        for w in WINDOW_RANGE:

            hits = []

            for j in range(i-40, i):

                if j >= w:

                    if groups[j] == groups[j-w]:
                        hits.append(1)
                    else:
                        hits.append(0)

            if len(hits) < 20:
                continue

            wr = np.mean(hits)

            ev = wr * WIN_PROFIT - (1-wr) * LOSE_LOSS

            if ev > best_ev:

                best_ev = ev
                best_wr = wr
                best_window = w

# ===== PREVIEW =====

        if best_window and best_wr > 0.28:

            preview_signal = groups[i-best_window]
            preview_window = best_window
            preview_wr = round(best_wr*100,2)
            preview_ev = round(best_ev,3)

# ===== COOLDOWN =====

        cooldown = 4

        if best_wr > 0.40:
            cooldown = 2

        elif best_wr > 0.35:
            cooldown = 3

# ===== CONFIRM SIGNAL =====

        if best_window and best_wr > 0.30 and best_ev > 0:

            if i - last_trade_round > cooldown:

                next_signal = groups[i-best_window]
                next_window = best_window
                next_wr = round(best_wr*100,2)
                next_ev = round(best_ev,3)

                signal_created_round = i

                state = "SIGNAL"

# ===== SAVE HISTORY =====

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

st.title("⚡ CYCLE QUANT ENGINE")

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

🚨 READY TO BET

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

st.dataframe(hist_df, use_container_width=True)

st.caption("CYCLE QUANT ENGINE | AUTO WINDOW SCAN")
