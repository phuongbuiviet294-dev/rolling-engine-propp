import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
CSV_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
WIN = 2.5
LOSS = 1
WINDOWS = range(8,19)

LOOKBACK_LONG = 3000   # dùng toàn bộ quá khứ
LOOKBACK_SHORT = 40    # trend ngắn hạn
GAP = 1

st.set_page_config(layout="wide")

# ================= GROUP =================
def get_group(n):
    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4

# ================= LOAD =================
@st.cache_data(ttl=5)
def load():
    return pd.read_csv(CSV_URL)

df = load()
numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine=[]
total_profit=0
last_trade=-999
next_signal=None
next_window=None

def calc_profit(hits):
    return sum(WIN if h else -LOSS for h in hits)

for i,n in enumerate(numbers):
    g=get_group(n)
    pred=None; hit=None; state="SCAN"; w_used=None

    # ===== EXECUTE =====
    if next_signal is not None:
        pred=next_signal
        w_used=next_window
        hit=1 if pred==g else 0
        total_profit+= WIN if hit else -LOSS
        state="TRADE"
        last_trade=i
        next_signal=None

    # ===== SIGNAL =====
    if len(engine)>50 and i-last_trade>=GAP:
        best_score=-999
        best_w=None
        best_pred=None

        for w in WINDOWS:
            if len(engine)<w+LOOKBACK_SHORT:
                continue

            # ===== LONG TERM =====
            hits_long=[]
            start=max(w,len(engine)-LOOKBACK_LONG)
            for j in range(start,len(engine)):
                if j>=w:
                    hits_long.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )

            if len(hits_long)<200:
                continue

            wr_long=np.mean(hits_long)
            profit_long=calc_profit(hits_long)

            if wr_long<0.28 and profit_long<=0:
                continue

            # ===== SHORT TERM =====
            hits_short=hits_long[-LOOKBACK_SHORT:]
            wr_short=np.mean(hits_short)
            profit_short=calc_profit(hits_short)

            if wr_short<0.35 and profit_short<-1:
                continue

            # ===== SCORE =====
            ev=wr_long*WIN-(1-wr_long)*LOSS
            score = profit_long*0.4 + profit_short*0.4 + ev*10

            if score>best_score:
                best_score=score
                best_w=w
                best_pred=engine[-w]["group"]

        if best_w is not None:
            next_signal=best_pred
            next_window=best_w
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

# ================= UI =================
st.title("🚀 TURBO HYBRID OPTIMIZED — REAL DATA MODE")

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits)*100 if hits else 0

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,1))
c3.metric("Winrate %",round(wr,2))

if next_signal:
    st.success(f"READY TO BET — NEXT GROUP: {next_signal} | Window: {next_window}")
else:
    st.info("Scanning…")

st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
