import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
BET_SIZE = 1.0

WINDOWS = [9,15]

LOOKBACK = 26
GAP = 4

STOPLOSS_STREAK = 4
PAUSE_ROUNDS = 6

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
def run_engine(numbers):
    engine=[]
    equity=0
    peak=0
    dd=0

    last_trade=-999
    next_signal=None

    loss_streak=0
    pause_until=-1

    for i,n in enumerate(numbers):
        g=get_group(n)

        predicted=None
        hit=None
        state="SCAN"

        # ===== PAUSE MODE =====
        if i < pause_until:
            state="PAUSE"

        # ===== EXECUTE TRADE =====
        elif next_signal is not None:
            predicted=next_signal
            hit=1 if predicted==g else 0

            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            pnl *= BET_SIZE
            equity += pnl

            state="TRADE"
            last_trade=i
            next_signal=None

            if hit:
                loss_streak=0
            else:
                loss_streak+=1

            if loss_streak>=STOPLOSS_STREAK:
                state="STOPLOSS"
                pause_until=i+PAUSE_ROUNDS
                loss_streak=0

        # ===== GENERATE SIGNAL =====
        if state=="SCAN" and len(engine)>=40 and i-last_trade>GAP:
            best_ev=-999
            best_w=None
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
                        best_w=w
                        best_wr=wr

            if best_w and best_wr>0.30 and best_ev>0:
                g1=engine[-best_w]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    state="SIGNAL"

        peak=max(peak,equity)
        dd=max(dd,peak-equity)

        engine.append({
            "round":i+1,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "equity":round(equity,2),
            "drawdown":round(peak-equity,2)
        })

    return engine,next_signal

engine,next_signal=run_engine(numbers)
dfh=pd.DataFrame(engine)

# ================= METRICS =================
st.title("🚀 PRO LIVE TRADING DASHBOARD")

c1,c2,c3,c4=st.columns(4)
c1.metric("Rounds",len(dfh))
c2.metric("Live Profit",dfh["equity"].iloc[-1])
c3.metric("Peak Profit",dfh["equity"].max())
c4.metric("Max Drawdown",dfh["drawdown"].max())

# ===== ADVANCED STATS =====
trades=dfh[dfh["hit"].notna()]
wins=(trades["hit"]==1).sum()
losses=(trades["hit"]==0).sum()
wr=wins/len(trades) if len(trades)>0 else 0

gross_win=wins*WIN_PROFIT*BET_SIZE
gross_loss=losses*LOSE_LOSS*BET_SIZE
pf=gross_win/gross_loss if gross_loss>0 else 0

expectancy=(wr*WIN_PROFIT-(1-wr)*LOSE_LOSS)*BET_SIZE

roi_100 = dfh["equity"].iloc[-1] / len(dfh) * 100

c5,c6,c7,c8=st.columns(4)
c5.metric("Winrate %",round(wr*100,2))
c6.metric("Profit Factor",round(pf,2))
c7.metric("Expectancy",round(expectancy,3))
c8.metric("ROI / 100 rounds",round(roi_100,2))

# ================= EQUITY CURVE =================
st.subheader("📈 Equity Curve")

fig = go.Figure()
fig.add_trace(go.Scatter(y=dfh["equity"], name="Equity"))
fig.add_trace(go.Scatter(y=dfh["equity"].cummax(), name="Peak", line=dict(dash="dot")))
fig.update_layout(height=400)
st.plotly_chart(fig, use_container_width=True)

# ================= DRAWDOWN =================
st.subheader("📉 Drawdown")

fig2 = go.Figure()
fig2.add_trace(go.Scatter(y=dfh["drawdown"], name="Drawdown"))
fig2.update_layout(height=300)
st.plotly_chart(fig2, use_container_width=True)

# ================= NEXT SIGNAL =================
st.subheader("🎯 Next Signal")
if next_signal:
    st.success(f"READY TO BET → GROUP {next_signal}")
else:
    st.info("Scanning...")

# ================= HISTORY =================
st.subheader("📋 Live History (No Repaint)")
st.dataframe(dfh.iloc[::-1],use_container_width=True)
