import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]

DRAW_THRESHOLD = 15
REOPT_ROUNDS = 400

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
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    return df

df = load()
numbers = df["number"].dropna().astype(int).tolist()

# ================= CORE ENGINE =================
def simulate(numbers, LOOKBACK, GAP):
    engine=[]
    total_profit=0
    last_trade_round=-999
    next_signal=None

    for i,n in enumerate(numbers):
        g=get_group(n)
        hit=None
        state="SCAN"

        if next_signal is not None:
            hit=1 if next_signal==g else 0
            total_profit += WIN_PROFIT if hit else -LOSE_LOSS
            state="TRADE"
            last_trade_round=i
            next_signal=None

        if len(engine)>=40 and i-last_trade_round>GAP:
            best_ev=-999
            best_window=None

            for w in WINDOWS:
                recent=[]
                start=max(w,len(engine)-LOOKBACK)
                for j in range(start,len(engine)):
                    if j>=w:
                        recent.append(
                            1 if engine[j]["group"]==engine[j-w]["group"] else 0
                        )
                if len(recent)>=20:
                    wr=np.mean(recent)
                    ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                    if ev>best_ev:
                        best_ev=ev
                        best_window=w
                        best_wr=wr

            if best_window and best_wr>0.29 and best_ev>0:
                g1=engine[-best_window]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    state="SIGNAL"

        engine.append({
            "group":g,
            "hit":hit,
            "state":state,
            "profit":total_profit
        })

    return total_profit,engine

# ================= PEAK LOCK =================
best_profit=-999
best_cfg=(26,3)

for LB in range(18,41):
    for GP in range(2,7):
        p,_=simulate(numbers,LB,GP)
        if p>best_profit:
            best_profit=p
            best_cfg=(LB,GP)

LOCK_LB,LOCK_GP=best_cfg

# ================= LIVE RUN =================
profit,engine=simulate(numbers,LOCK_LB,LOCK_GP)
current_profit=engine[-1]["profit"]

# ================= REGIME CHECK =================
peak_profit=max(x["profit"] for x in engine)
drawdown=peak_profit-current_profit

if drawdown>DRAW_THRESHOLD:
    recent_numbers=numbers[-REOPT_ROUNDS:]
    new_best=-999
    new_cfg=best_cfg

    for LB in range(18,41):
        for GP in range(2,7):
            p,_=simulate(recent_numbers,LB,GP)
            if p>new_best:
                new_best=p
                new_cfg=(LB,GP)

    if new_best>=best_profit*0.9:
        LOCK_LB,LOCK_GP=new_cfg
        profit,engine=simulate(numbers,LOCK_LB,LOCK_GP)

# ================= UI =================
st.title("🧠 PEAK LOCK AI REGIME ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(engine[-1]["profit"],2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Locked Config → Lookback={LOCK_LB} | Gap={LOCK_GP}")

st.subheader("History")
hist=pd.DataFrame(engine)
st.dataframe(hist.iloc[::-1],use_container_width=True)
