# ==========================================
# TURBO TREND PRO MAX C++ — LIVE ONLINE
# ==========================================

import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS  = 1

WINDOW_RANGE = range(8,19)

SHORT_LOOKBACK = 40
COOLDOWN_ROUNDS = 4
LOSS_STREAK_LIMIT = 4
HARD_STOP_DD = -15

st.set_page_config(layout="wide")

# ================= GROUP =================
def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

# ================= LOAD DATA =================
@st.cache_data(ttl=AUTO_REFRESH)
def load_data():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load_data()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
def calc_hit_rate(x): return np.mean(x) if len(x)>0 else 0
def calc_profit(x): return sum(x)
def calc_ev(hit): return hit*WIN_PROFIT-(1-hit)*LOSE_LOSS

def window_score(p,h,e):
    return p*0.5 + h*0.3 + e*0.2

engine=[]
total_profit=0
loss_streak=0
cooldown=0
last_trade_round=-999
next_signal=None
next_window=None
next_hit=None
next_ev=None

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None
    hit=None
    pnl=None
    state="SCAN"

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        hit=1 if predicted==g else 0
        pnl = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit += pnl

        if pnl<0: loss_streak+=1
        else: loss_streak=0

        if loss_streak>=LOSS_STREAK_LIMIT:
            cooldown=COOLDOWN_ROUNDS

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== COOLDOWN =====
    if cooldown>0:
        cooldown-=1

    # ===== SELECT WINDOW =====
    best=None
    best_score=-999

    if len(engine)>=SHORT_LOOKBACK:
        for w in WINDOW_RANGE:
            if len(engine)<w+SHORT_LOOKBACK:
                continue

            recent=engine[-SHORT_LOOKBACK:]
            hits=[x["hit"] for x in recent if x["hit"] is not None]
            profits=[x["pnl"] for x in recent if x["pnl"] is not None]

            if len(hits)<10: continue

            h=calc_hit_rate(hits)
            p=calc_profit(profits)
            e=calc_ev(h)

            s=window_score(p,h,e)
            if s>best_score:
                best_score=s
                best=(w,h,p,e)

    # ===== GENERATE SIGNAL =====
    if best and cooldown==0 and total_profit>HARD_STOP_DD:
        w,h,p,e=best
        if i-last_trade_round>=1 and h>0.35:
            g1=engine[-w]["group"] if len(engine)>=w else None
            if g1 and engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=w
                next_hit=h
                next_ev=e
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "pnl":pnl,
        "state":state
    })

# ================= UI =================
st.title("🚀 TURBO TREND PRO MAX C++ — LIVE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    HitRate: {round(next_hit*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning market...")

# ================= HISTORY =================
st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
