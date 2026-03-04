import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(5,31)

WINDOW_LOCK_ROUNDS = 60
RESCAN_THRESHOLD = 0.28

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

locked_window = None
lock_start_round = 0

hits_history = []

next_signal = None

# ================= WINDOW SCAN ================= #

def find_best_window(i):

    best_w = None
    best_ev = -999
    best_wr = 0

    for w in WINDOW_RANGE:

        hits = []

        for j in range(i-80, i):

            if j >= w:

                if groups[j] == groups[j-w]:
                    hits.append(1)
                else:
                    hits.append(0)

        if len(hits) < 30:
            continue

        wr = np.mean(hits)

        ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS

        if ev > best_ev:

            best_ev = ev
            best_wr = wr
            best_w = w

    return best_w, best_wr, best_ev


# ================= ENGINE ================= #

for i,n in enumerate(numbers):

    g = groups[i]

    predicted = None
    hit = None
    state = "SCAN"

# ===== RESCAN WINDOW =====

    if locked_window is None and i > 100:

        w,wr,ev = find_best_window(i)

        if w is not None:

            locked_window = w
            lock_start_round = i

# ===== TRADE =====

    if locked_window and i > locked_window:

        predicted = groups[i-locked_window]

        hit = 1 if predicted == g else 0

        if hit:

            total_profit += WIN_PROFIT

        else:

            total_profit -= LOSE_LOSS

        hits_history.append(hit)

        state = "TRADE"

# ===== PERFORMANCE CHECK =====

    if locked_window and len(hits_history) > 40:

        wr = np.mean(hits_history[-40:])

        if wr < RESCAN_THRESHOLD:

            locked_window = None
            hits_history = []

# ===== WINDOW TIMEOUT =====

    if locked_window and (i - lock_start_round) > WINDOW_LOCK_ROUNDS:

        locked_window = None
        hits_history = []

# ===== NEXT SIGNAL =====

    if locked_window and i > locked_window:

        next_signal = groups[i-locked_window]

# ===== SAVE HISTORY =====

    engine.append({

        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": locked_window,
        "state": state

    })


# ================= DASHBOARD ================= #

st.title("⚡ ADAPTIVE CYCLE ENGINE")

col1,col2,col3 = st.columns(3)

col1.metric("Total Rounds", len(engine))
col2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr = np.mean(hits)

    col3.metric("Winrate %", round(wr*100,2))


# ===== NEXT GROUP =====

if next_signal:

    st.markdown(f"""
<div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:28px;font-weight:bold'>

🚨 NEXT GROUP TO BET

GROUP: {next_signal}

WINDOW: {locked_window}

</div>
""",unsafe_allow_html=True)

else:

    st.info("Scanning window...")


# ===== HISTORY =====

st.subheader("History")

hist_df = pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)

st.caption("ADAPTIVE CYCLE ENGINE | WINDOW LOCK MODE")
