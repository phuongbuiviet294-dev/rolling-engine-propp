import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

st.set_page_config(layout="wide")

# ================= BASIC ================= #

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

engine = []

# ================= CORE ENGINE ================= #

def rolling_wr(data, window):
    if len(data) < window:
        return None
    recent = data[-window:]
    hits = [x["hit"] for x in recent if x["hit"] is not None]
    if len(hits) == 0:
        return None
    return sum(hits) / len(hits)

def hits_26(data, w):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    return sum(
        1 for i in range(w, 26)
        if recent[i]["group"] == recent[i-w]["group"]
    )

# ================= WALK FORWARD ================= #

condition_hits = []
system_on = True

for i, n in enumerate(numbers):

    g = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"
    p_adj_selected = None
    selected_window = None

    if len(engine) >= 40:

        # ===== REGIME FILTER =====
        rw20 = rolling_wr(engine, 20)
        high_density = any(hits_26(engine, w) >= 8 for w in range(6,20))

        if rw20 and rw20 > 0.28 and high_density and system_on:

            candidates = []

            for w in range(6,20):

                total = 0
                wins = 0

                # historical forward test
                for j in range(w, len(engine)-1):
                    if hits_26(engine[:j], w) >= 8:
                        total += 1
                        if engine[j]["group"] == engine[j-w]["group"]:
                            wins += 1

                if total >= 25:
                    p_adj = (wins + 1) / (total + 2)

                    # momentum
                    wr20 = rolling_wr(engine[-20:], 20) if len(engine)>=20 else None
                    wr40 = rolling_wr(engine[-40:], 40) if len(engine)>=40 else None

                    momentum = 0
                    if wr20 and wr40:
                        momentum = wr20 - wr40

                    if p_adj > 0.31 and momentum >= 0:
                        candidates.append((w, p_adj))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                selected_window = candidates[0][0]
                p_adj_selected = round(candidates[0][1]*100,2)

                if len(engine) >= selected_window:
                    predicted = engine[-selected_window]["group"]
                    hit = 1 if predicted == g else 0
                    state = "TRADE"

                    condition_hits.append(hit)

                    # ===== META PROTECTION =====
                    if len(condition_hits) >= 25:
                        recent_wr = sum(condition_hits[-25:]) / 25
                        if recent_wr < 0.28:
                            system_on = False
                        elif recent_wr > 0.30:
                            system_on = True

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": selected_window,
        "p_adj_%": p_adj_selected,
        "state": state
    })

# ================= DASHBOARD ================= #

st.title("🚀 PRO FINAL ENGINE – STABLE")

col1,col2,col3,col4 = st.columns(4)

col1.metric("Total Rounds", len(engine))
col2.metric("System Status", "ON" if system_on else "OFF")
col3.metric("Total Trades", len(condition_hits))
col4.metric("Winrate", 
            round((sum(condition_hits)/len(condition_hits))*100,2) 
            if len(condition_hits)>0 else 0)

# EV calculation
if len(condition_hits)>0:
    wr = sum(condition_hits)/len(condition_hits)
    ev = wr*25 - (1-wr)*10
    st.metric("EV per Trade", round(ev,2))

# HISTORY
st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)

st.caption("PRO FINAL – Bayesian Dynamic | Regime Adaptive | Meta Protection | No Overfit")
