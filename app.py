import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW = 9
LOOKBACK_RANGE = range(18, 29)
GAP_RANGE = range(3, 6)

RELOCK_DRAWDOWN = 10
RECENT_SCAN = 1200

st.set_page_config(layout="wide")

# ================= GROUP =================
def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

# ================= LOAD =================
@st.cache_data(ttl=5)
def load():
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    return df

df = load()
numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE CORE =================
def simulate(lookback, gap, nums):
    engine = []
    profit = 0
    last_trade = -999
    next_signal = None
    peak_profit = 0

    for i,n in enumerate(nums):
        g = get_group(n)
        hit = None
        state = "SCAN"

        if next_signal is not None:
            hit = 1 if next_signal == g else 0
            profit += WIN_PROFIT if hit else -LOSE_LOSS
            state = "TRADE"
            last_trade = i
            next_signal = None

        if len(engine) >= lookback and i - last_trade > gap:
            hits=[]
            for j in range(len(engine)-lookback, len(engine)):
                if j>=WINDOW:
                    hits.append(
                        1 if engine[j]["group"]==engine[j-WINDOW]["group"] else 0
                    )
            if len(hits)>=12:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                if ev>0 and wr>0.27:
                    g1=engine[-WINDOW]["group"]
                    if engine[-1]["group"]!=g1:
                        next_signal=g1
                        state="SIGNAL"

        peak_profit=max(peak_profit,profit)

        engine.append({
            "round":i+1,
            "group":g,
            "hit":hit,
            "profit":profit,
            "peak":peak_profit,
            "dd":peak_profit-profit,
            "state":state
        })

    return profit, engine

# ================= FIND BEST LOCK =================
recent_numbers = numbers[-RECENT_SCAN:]

best_profit = -999
best_cfg = None

for lb in LOOKBACK_RANGE:
    for gp in GAP_RANGE:
        p,_ = simulate(lb,gp,recent_numbers)
        if p>best_profit:
            best_profit=p
            best_cfg=(lb,gp)

LOOKBACK,GAP=best_cfg

# ================= RUN LIVE =================
live_profit, engine = simulate(LOOKBACK,GAP,numbers)

# ================= AUTO RELOCK =================
dd = engine[-1]["dd"]
if dd >= RELOCK_DRAWDOWN:
    st.warning("♻️ Re-locking due to drawdown...")
    best_profit=-999
    for lb in LOOKBACK_RANGE:
        for gp in GAP_RANGE:
            p,_=simulate(lb,gp,numbers[-RECENT_SCAN:])
            if p>best_profit:
                best_profit=p
                LOOKBACK,GAP=lb,gp
    live_profit, engine = simulate(LOOKBACK,GAP,numbers)

# ================= UI =================
st.title("🔒 AUTO RELOCK PROFIT ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Live Profit",round(live_profit,2))
hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Window=9 | Lookback={LOOKBACK} | Gap={GAP}")

st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
