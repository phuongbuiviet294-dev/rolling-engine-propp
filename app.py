import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,15]

# ===== LOCK CONFIG (engine hiện tại của bạn) =====
LOCK_LOOKBACK = 26
LOCK_GAP = 4

st.set_page_config(layout="wide")

# ================= LOAD DATA =================
@st.cache_data(ttl=AUTO_REFRESH)
def load():
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    return df

df = load()
numbers = df["number"].dropna().astype(int).tolist()

# ================= GROUP =================
def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

# ================= ENGINE =================
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

            if best_window and best_wr>0.29 and best_ev>-0.01:
                g1=engine[-best_window]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    state="SIGNAL"

        engine.append({
            "round":i+1,
            "group":g,
            "hit":hit,
            "state":state,
            "profit":total_profit
        })

    return engine

engine = simulate(numbers, LOCK_LOOKBACK, LOCK_GAP)
hist = pd.DataFrame(engine)

# ================= GLOBAL METRICS =================
global_profit = hist["profit"].iloc[-1]
peak_profit = hist["profit"].max()
drawdown = peak_profit - global_profit

hits = hist["hit"].dropna()
winrate = hits.mean() if len(hits)>0 else 0

wins = (hits==1).sum()
losses = (hits==0).sum()

profit_factor = (wins*WIN_PROFIT)/(losses*LOSE_LOSS) if losses>0 else 0
expectancy = winrate*WIN_PROFIT - (1-winrate)*LOSE_LOSS

roi_100 = global_profit/len(hist)*100 if len(hist)>0 else 0

# ================= STREAK =================
streak=0
max_loss_streak=0
for h in hits:
    if h==0:
        streak+=1
        max_loss_streak=max(max_loss_streak,streak)
    else:
        streak=0

# ================= EQUITY CURVE =================
hist["peak"] = hist["profit"].cummax()
hist["dd"] = hist["peak"] - hist["profit"]

# ================= UI =================
st.title("🧠 PRO ANALYTICS DASHBOARD — REAL PERFORMANCE")

c1,c2,c3,c4 = st.columns(4)
c1.metric("Global Profit", round(global_profit,2))
c2.metric("Peak Profit", round(peak_profit,2))
c3.metric("Max Drawdown", round(drawdown,2))
c4.metric("ROI / 100 rounds", round(roi_100,2))

c5,c6,c7,c8 = st.columns(4)
c5.metric("Winrate %", round(winrate*100,2))
c6.metric("Profit Factor", round(profit_factor,2))
c7.metric("Expectancy", round(expectancy,3))
c8.metric("Max Loss Streak", int(max_loss_streak))

st.caption(f"Locked Config → Lookback={LOCK_LOOKBACK} | Gap={LOCK_GAP}")

# ================= CHARTS =================
st.subheader("📈 Equity Curve")
st.line_chart(hist.set_index("round")["profit"])

st.subheader("📉 Drawdown")
st.line_chart(hist.set_index("round")["dd"])

# ================= REGIME STATUS =================
st.subheader("🧭 Engine Health")

if expectancy > 0 and drawdown < peak_profit*0.3:
    st.success("🟢 Healthy Regime — Engine has statistical edge")
elif expectancy > 0:
    st.warning("🟡 Profitable but volatile — Risky regime")
else:
    st.error("🔴 Negative Expectancy — No statistical edge")

# ================= HISTORY =================
st.subheader("📋 Trade History")
st.dataframe(hist.iloc[::-1], use_container_width=True)
