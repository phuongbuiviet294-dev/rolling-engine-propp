import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(8,18)   # adaptive window
CYCLE_SIZE = 120             # rounds per cycle
MIN_WR = 0.30
MIN_EV = 0.02
MIN_SAMPLES = 20
GAP = 4

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
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine=[]
profit=0
last_trade=-999
next_signal=None
next_window=None
next_wr=None
next_ev=None

def best_window_cycle(engine, start_idx):
    best_w=None; best_ev=-999; best_wr=0; best_samples=0

    for w in WINDOW_RANGE:
        hits=[]
        for j in range(start_idx,len(engine)):
            if j>=w:
                hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)

        if len(hits)>=MIN_SAMPLES:
            wr=np.mean(hits)
            ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
            if ev>best_ev:
                best_ev=ev; best_w=w; best_wr=wr; best_samples=len(hits)

    return best_w,best_wr,best_ev,best_samples

for i,n in enumerate(numbers):
    g=get_group(n)
    pred=None; hit=None; state="SCAN"
    used_w=None; used_wr=None; used_ev=None

    # ===== EXECUTE =====
    if next_signal is not None:
        pred=next_signal
        used_w=next_window
        used_wr=next_wr
        used_ev=next_ev

        hit=1 if pred==g else 0
        profit += WIN_PROFIT if hit else -LOSE_LOSS

        state="TRADE"
        last_trade=i
        next_signal=None

    # ===== GENERATE =====
    if len(engine)>=40 and i-last_trade>GAP:

        cycle_start = max(0, len(engine)-CYCLE_SIZE)

        w,wr,ev,samples = best_window_cycle(engine, cycle_start)

        if (
            w is not None
            and wr>MIN_WR
            and ev>MIN_EV
            and samples>=MIN_SAMPLES
        ):
            g1=engine[-w]["group"]
            if engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=w
                next_wr=wr
                next_ev=ev
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "pred":pred,
        "hit":hit,
        "window":used_w,
        "wr":None if used_wr is None else round(used_wr*100,2),
        "ev":None if used_ev is None else round(used_ev,3),
        "state":state
    })

# ================= UI =================
st.title("🧠 CYCLE-ADAPTIVE WINDOW AI")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {round(next_wr*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("No valid signal")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
