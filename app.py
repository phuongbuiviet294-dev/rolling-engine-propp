import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

CONF_THRESHOLD = 0.45

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

next_signal = None

# ================= ENGINE ================= #

for i,n in enumerate(numbers):

    g = groups[i]

    predicted = None
    hit = None
    state = "SCAN"

# ===== BUILD TRANSITION MATRIX =====

    if i > 40:

        matrix = np.zeros((4,4))

        for j in range(i-40,i-1):

            a = groups[j]-1
            b = groups[j+1]-1

            matrix[a][b] += 1

        for r in range(4):

            s = sum(matrix[r])

            if s > 0:
                matrix[r] /= s

# ===== PREDICT NEXT =====

        last = groups[i-1]-1

        probs = matrix[last]

        best = np.argmax(probs)

        confidence = probs[best]

        if confidence > CONF_THRESHOLD:

            next_signal = best + 1

        else:

            next_signal = None

# ===== TRADE =====

    if next_signal is not None:

        predicted = next_signal

        hit = 1 if predicted == g else 0

        if hit:

            total_profit += WIN_PROFIT

        else:

            total_profit -= LOSE_LOSS

        state = "TRADE"

# ===== SAVE HISTORY =====

    engine.append({

        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state

    })

# ================= DASHBOARD ================= #

st.title("🔥 BURST PATTERN ENGINE")

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

</div>
""",unsafe_allow_html=True)

else:

    st.info("No strong pattern detected")

# ===== HISTORY =====

st.subheader("History")

hist_df = pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df, use_container_width=True)

st.caption("BURST PATTERN ENGINE | MARKOV SPIKE DETECTOR")
