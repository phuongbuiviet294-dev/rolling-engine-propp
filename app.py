import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]

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
def run_engine(LOOKBACK, GAP):
    engine = []
    total_profit = 0
    last_trade_round = -999
    cooldown_until = -1

    next_signal = None
    next_window = None
    next_wr = None
    next_ev = None

    for i, n in enumerate(numbers):
        g = get_group(n)
        predicted = None
        hit = None
        state = "SCAN"

        # ===== EXECUTE =====
        if next_signal is not None:
            predicted = next_signal
            hit = 1 if predicted == g else 0
            total_profit += WIN_PROFIT if hit else -LOSE_LOSS
            state = "TRADE"
            last_trade_round = i
            next_signal = None

        # ===== PROTECT PROFIT =====
        allow_trade = True

        # Cooldown zone
        if i < cooldown_until:
            allow_trade = False

        # Drawdown brake
        recent_hits = [x["hit"] for x in engine[-50:] if x["hit"] is not None]
        if len(recent_hits) >= 20:
            recent_profit = sum([WIN_PROFIT if h==1 else -LOSE_LOSS for h in recent_hits])
            if recent_profit <= 0:
                allow_trade = False

        # Skip loss zone
        last6 = [x["hit"] for x in engine[-6:] if x["hit"] is not None]
        if len(last6) == 6 and sum(last6) <= 2:
            cooldown_until = i + 20
            allow_trade = False

        # Volatility filter
        recent_groups = [x["group"] for x in engine[-30:]]
        if len(recent_groups) >= 30:
            changes = sum([1 for a,b in zip(recent_groups, recent_groups[1:]) if a!=b])
            if changes > 22:
                allow_trade = False

        # Momentum mode
        GAP_USED = GAP
        last6 = [x["hit"] for x in engine[-6:] if x["hit"] is not None]
        if len(last6)==6 and sum(last6)>=4:
            GAP_USED = max(2, GAP-1)

        # ===== GENERATE =====
        if allow_trade and len(engine)>=40 and i-last_trade_round>GAP_USED:
            best_window=None
            best_ev=-999
            best_wr=0

            for w in WINDOWS:
                hits=[]
                start=max(w,len(engine)-LOOKBACK)
                for j in range(start,len(engine)):
                    if j>=w:
                        hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)
                if len(hits)>=20:
                    wr=np.mean(hits)
                    ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                    if ev>best_ev:
                        best_ev=ev
                        best_window=w
                        best_wr=wr

            if best_window and best_wr>0.29 and best_ev>0:
                g1=engine[-best_window]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    next_window=best_window
                    next_wr=best_wr
                    next_ev=best_ev
                    state="SIGNAL"

        engine.append({
            "round":i+1,
            "number":n,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state
        })

    return total_profit,engine,next_signal,next_window,next_wr,next_ev

# ================= AUTO OPT =================
best_profit=-999
best_cfg=None
best_engine=None
best_next=None

for LOOKBACK in range(20,41):
    for GAP in range(3,7):
        profit,eng,ns,nw,nwr,nev=run_engine(LOOKBACK,GAP)
        if profit>best_profit:
            best_profit=profit
            best_cfg=(LOOKBACK,GAP)
            best_engine=eng
            best_next=(ns,nw,nwr,nev)

LOOKBACK,GAP=best_cfg
engine=best_engine
next_signal,next_window,next_wr,next_ev=best_next

# ================= UI =================
st.title("🚀 AI BETTING ENGINE — PRO MAX (FLAT BET)")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(best_profit,2))
hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"PRO MAX | Lookback={LOOKBACK} | Gap={GAP}")

if next_signal:
    st.success(f"🎯 NEXT GROUP: {next_signal} | Window={next_window} | WR={round(next_wr*100,2)}% | EV={round(next_ev,3)}")
else:
    st.info("No valid signal")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
