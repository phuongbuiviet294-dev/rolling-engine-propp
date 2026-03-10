import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = range(8,18)   # 🔥 Adaptive windows 8→17
LOOKBACK = 28
GAP = 4

st.set_page_config(layout="wide")

# ================= GROUP =================
def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4

# ================= LOAD =================
df = pd.read_csv(GOOGLE_SHEET_CSV)
numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine = []
profit = 0
last_trade = -999

next_signal = None
next_window = None
next_wr = None
next_ev = None

# ================= ADAPTIVE WINDOW =================
def best_window_now(engine):
    best_w = None
    best_ev = -999
    best_wr = 0
    
    for w in WINDOWS:
        hits = []
        start = max(w, len(engine) - LOOKBACK)

        for j in range(start, len(engine)):
            if j >= w:
                hits.append(
                    1 if engine[j]["group"] == engine[j-w]["group"] else 0
                )

        if len(hits) >= 20:
            wr = np.mean(hits)
            ev = wr * WIN_PROFIT - (1-wr) * LOSE_LOSS

            if ev > best_ev:
                best_ev = ev
                best_w = w
                best_wr = wr

    return best_w, best_wr, best_ev

# ================= LOOP =================
for i,n in enumerate(numbers):
    g = get_group(n)
    pred=None; hit=None; state="SCAN"
    used_w=None; used_wr=None; used_ev=None

    # ===== EXECUTE TRADE =====
    if next_signal is not None:
        pred = next_signal
        used_w = next_window
        used_wr = next_wr
        used_ev = next_ev

        hit = 1 if pred == g else 0
        profit += WIN_PROFIT if hit else -LOSE_LOSS

        state="TRADE"
        last_trade=i
        next_signal=None

    # ===== GENERATE SIGNAL =====
    if len(engine)>=40 and i-last_trade>=GAP:
        w,wr,ev = best_window_now(engine)

        if w is not None and wr>0.30 and ev>0:
            signal_group = engine[-w]["group"]

            # timing filter
            if engine[-1]["group"] != signal_group:
                next_signal = signal_group
                next_window = w
                next_wr = wr
                next_ev = ev
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "pred":pred,
        "hit":hit,
        "window":used_w,
        "wr":used_wr,
        "ev":used_ev,
        "state":state
    })

# ================= DASHBOARD =================
st.title("🧠 ADAPTIVE WINDOW AI")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Profit", round(profit,2))
hits=[x["hit"] for x in engine if x["hit"]!=None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr*100,2))

# ================= NEXT =================
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
        <br>WR: {round(next_wr*100,2)}%
        <br>EV: {round(next_ev,3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("No valid signal")

# ================= HISTORY =================
st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)
