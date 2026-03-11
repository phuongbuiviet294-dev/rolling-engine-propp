import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9]

LOOKBACK = 20
GAP = 1

FLOW_RANGE = 6        # số round tính profit flow
HIT_RANGE = 8         # số round tính hit trend
MIN_HIT_RATE = 0.40   # hit ≥40%
STOP_LOSS_FLOW = -3   # stop khi âm sâu

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
total_profit=0
last_trade_round=-999

next_signal=None
next_window=None
next_wr=None
next_ev=None

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None; wr_used=None; ev_used=None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        wr_used=next_wr
        ev_used=next_ev

        hit=1 if predicted==g else 0
        pnl = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit += pnl

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== FLOW PROFIT =====
    recent_pnls=[]
    for r in engine[-FLOW_RANGE:]:
        if r["hit"] is not None:
            recent_pnls.append(WIN_PROFIT if r["hit"]==1 else -LOSE_LOSS)
    recent_profit=sum(recent_pnls)

    # ===== HIT TREND =====
    recent_hits=[r["hit"] for r in engine[-HIT_RANGE:] if r["hit"] is not None]
    hit_rate=np.mean(recent_hits) if recent_hits else 0.5

    # ===== GENERATE SIGNAL =====
    if len(engine)>=40 and i-last_trade_round>GAP:

        best_w=None; best_ev=-999; best_wr=0

        for w in WINDOWS:
            hits=[]
            start=max(w,len(engine)-LOOKBACK)
            for j in range(start,len(engine)):
                if j>=w:
                    hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)

            if len(hits)>=15:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                if ev>best_ev:
                    best_ev=ev; best_w=w; best_wr=wr

        if best_w is not None:
            g1=engine[-best_w]["group"]

            # ===== HYBRID ENTRY =====
            if (
                best_ev>0 and
                recent_profit>=0 and
                hit_rate>=MIN_HIT_RATE and
                engine[-1]["group"]!=g1
            ):
                next_signal=g1
                next_window=best_w
                next_wr=best_wr
                next_ev=best_ev
                state="SIGNAL"

    # ===== HARD STOP =====
    if recent_profit<=STOP_LOSS_FLOW:
        next_signal=None

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit_flow":recent_profit,
        "hit_rate":round(hit_rate*100,1),
        "window":window_used,
        "wr":None if wr_used is None else round(wr_used*100,1),
        "ev":None if ev_used is None else round(ev_used,3),
        "state":state
    })

# ================= UI =================
st.title("🧠 FLOW + HIT HYBRID ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

# ================= NEXT SIGNAL =================
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
    st.info("No signal — Waiting for Profit Flow")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
