import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9,15]

LOSS_STREAK_STOP = 6
DRAWDOWN_STOP = 22
COOLDOWN_ROUNDS = 25

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

# ================= ENGINE =================
def run_engine(numbers, LOOKBACK, GAP):
    engine=[]
    total_profit=0
    peak_profit=0
    loss_streak=0
    cooldown=0
    last_trade_round=-999
    next_signal=None

    for i,n in enumerate(numbers):
        g=get_group(n)

        predicted=None
        hit=None
        state="SCAN"

        # ===== COOLDOWN =====
        if cooldown>0:
            cooldown-=1
            state="COOLDOWN"

        # ===== EXECUTE TRADE =====
        elif next_signal is not None:
            predicted=next_signal
            hit=1 if predicted==g else 0

            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += pnl

            if hit:
                loss_streak=0
            else:
                loss_streak+=1

            state="TRADE"
            last_trade_round=i
            next_signal=None

        # ===== UPDATE PEAK & DD =====
        peak_profit=max(peak_profit,total_profit)
        drawdown=peak_profit-total_profit

        # ===== RISK GUARD =====
        if loss_streak>=LOSS_STREAK_STOP or drawdown>=DRAWDOWN_STOP:
            cooldown=COOLDOWN_ROUNDS
            state="RISK_STOP"

        # ===== REGIME FILTER =====
        allow_trade=True
        recent_hits=[x["hit"] for x in engine[-30:] if x["hit"] is not None]
        if len(recent_hits)>=15:
            if np.mean(recent_hits)<0.27:
                allow_trade=False

        # ===== GENERATE SIGNAL =====
        if (
            allow_trade and
            cooldown==0 and
            len(engine)>=40 and
            i-last_trade_round>GAP
        ):
            best_ev=-999
            best_window=None
            best_wr=0

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

            if best_window and best_wr>0.29 and best_ev>0.05:
                g1=engine[-best_window]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    state="SIGNAL"

        engine.append({
            "round":i+1,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":round(total_profit,2),
            "peak":round(peak_profit,2),
            "dd":round(drawdown,2)
        })

    return total_profit,engine,next_signal

# ================= LOCK OPTIMIZER =================
best_profit=-999
best_cfg=(26,3)

for LB in range(18,33):
    for GP in range(2,6):
        p,_,_=run_engine(numbers,LB,GP)
        if p>best_profit:
            best_profit=p
            best_cfg=(LB,GP)

LOCK_LB,LOCK_GP=best_cfg

profit,engine,next_signal=run_engine(numbers,LOCK_LB,LOCK_GP)

# ================= UI =================
st.title("🚀 LONG RUN PRO — PROFIT BIAS MODE")

c1,c2,c3,c4=st.columns(4)
c1.metric("Rounds",len(engine))
c2.metric("Profit",engine[-1]["profit"])
c3.metric("Peak",engine[-1]["peak"])

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c4.metric("Winrate %",round(wr*100,2))

st.caption(f"Locked Config → Lookback={LOCK_LB} | Gap={LOCK_GP}")

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.success(f"🎯 NEXT GROUP: {next_signal}")
else:
    st.info("Scanning...")

# ================= HISTORY =================
st.subheader("History")
hist=pd.DataFrame(engine)
st.dataframe(hist.iloc[::-1],use_container_width=True)
