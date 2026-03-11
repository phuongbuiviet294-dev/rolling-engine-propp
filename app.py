import streamlit as st
import pandas as pd
import numpy as np

# ===== CONFIG =====
CSV_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
WIN = 2.5
LOSS = 1
WINDOWS = range(8,19)
LOOKBACK = 30

st.set_page_config(layout="wide")

# ===== GROUP =====
def get_group(n):
    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4

# ===== LOAD =====
@st.cache_data(ttl=5)
def load():
    return pd.read_csv(CSV_URL)

df = load()
nums = df["number"].dropna().astype(int).tolist()

# ===== ENGINE =====
engine=[]
total_profit=0
last_trade=-999
next_signal=None
next_window=None

def calc_profit(hits):
    return sum(WIN if h else -LOSS for h in hits)

for i,n in enumerate(nums):
    g=get_group(n)
    pred=None; hit=None; state="SCAN"; w_used=None

    # ===== EXECUTE =====
    if next_signal:
        pred=next_signal
        w_used=next_window
        hit=1 if pred==g else 0
        total_profit += WIN if hit else -LOSS
        state="TRADE"
        last_trade=i
        next_signal=None

    # ===== MARKET REGIME =====
    recent_hits=[x["hit"] for x in engine[-20:] if x["hit"] is not None]
    recent_wr=np.mean(recent_hits) if recent_hits else 0.5

    if recent_wr>0.55:
        GAP=1
    elif recent_wr>0.45:
        GAP=2
    else:
        GAP=3

    # ===== SIGNAL ENGINE =====
    if len(engine)>60 and i-last_trade>=GAP:

        candidates=[]

        for w in WINDOWS:
            if len(engine)<=w+LOOKBACK:
                continue

            hits=[]
            for j in range(w,len(engine)):
                hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)

            if len(hits)<120:
                continue

            wr_long=np.mean(hits)
            ev_long=wr_long*WIN-(1-wr_long)*LOSS

            recent=hits[-LOOKBACK:]
            wr_short=np.mean(recent)
            profit_short=calc_profit(recent)

            # ===== ENTRY CONDITIONS =====
            if not (
                profit_short>0 or
                wr_short>=0.38 or
                ev_long>0
            ):
                continue

            score = (
                profit_short*3 +
                wr_short*12 +
                ev_long*4
            )

            candidates.append((score,w,wr_short,profit_short,ev_long))

        # ===== PICK BEST =====
        if candidates:
            candidates.sort(reverse=True)
            _,w,wr_s,pf_s,ev_l = candidates[0]

            next_signal = engine[-w]["group"]
            next_window = w
            state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":pred,
        "hit":hit,
        "window":w_used,
        "state":state,
        "total_profit":round(total_profit,1)
    })

# ===== UI =====
st.title("🔥 TREND MASTER — REAL TRADE ENGINE")

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits)*100 if hits else 0

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,1))
c3.metric("Winrate %",round(wr,2))

if next_signal:
    st.success(f"🚨 READY TO BET — NEXT GROUP: {next_signal} | Window: {next_window}")
else:
    st.info("Scanning trend…")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
