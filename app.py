import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,15]

DRAW_THRESHOLD = 15
REOPT_ROUNDS = 200

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

    loss_streak=0
    pause_until=-1

    for i,n in enumerate(numbers):
        g=get_group(n)

        predicted=None
        hit=None
        state="SCAN"

        # ===== EXECUTE TRADE =====
        if next_signal is not None and i>pause_until:
            predicted=next_signal
            hit=1 if predicted==g else 0
            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += pnl
            state="TRADE"
            last_trade_round=i
            next_signal=None

            if hit==0:
                loss_streak+=1
            else:
                loss_streak=0

            # ===== STOPLOSS PAUSE =====
            if loss_streak>=5:
                pause_until=i+GAP
                state="COOLDOWN"

        # ===== GENERATE SIGNAL =====
        if len(engine)>=40 and i-last_trade_round>GAP and i>pause_until:
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
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":round(total_profit,2)
        })

    return total_profit,engine,next_signal

# ================= PEAK LOCK =================
best_profit=-999
best_cfg=(26,4)

for LB in range(18,29):
    for GP in range(3,7):
        p,_,_=simulate(numbers,LB,GP)
        if p>best_profit:
            best_profit=p
            best_cfg=(LB,GP)

LOCK_LB,LOCK_GP=best_cfg

# ================= LIVE RUN =================
profit,engine,next_signal=simulate(numbers,LOCK_LB,LOCK_GP)

# ================= DASHBOARD =================
st.title("🚀 PRO MAX ANALYTICS ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(engine[-1]["profit"],2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Locked Config → Lookback={LOCK_LB} | Gap={LOCK_GP}")

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>
        🚨 READY TO BET 🚨<br>
        🎯 NEXT GROUP: {next_signal}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

# ================= ANALYTICS =================
profits = [x["profit"] for x in engine]
peak_curve = np.maximum.accumulate(profits)
drawdowns = peak_curve - profits

peak_profit = max(profits)
live_profit = profits[-1]
max_dd = max(drawdowns)

wins = sum(1 for x in hits if x==1)
losses = sum(1 for x in hits if x==0)
total_trades = wins + losses

winrate = wins / total_trades if total_trades else 0
gross_win = wins * WIN_PROFIT
gross_loss = losses * LOSE_LOSS
profit_factor = gross_win / gross_loss if gross_loss else 0
expectancy = (winrate * WIN_PROFIT) - ((1 - winrate) * LOSE_LOSS)
roi_100 = (live_profit / len(engine)) * 100 if engine else 0

# ===== Streaks =====
max_loss_streak=0
cur_loss=0
for h in hits:
    if h==0:
        cur_loss+=1
        max_loss_streak=max(max_loss_streak,cur_loss)
    else:
        cur_loss=0

# ================= EQUITY CURVE =================
st.subheader("📈 Equity Curve")
st.line_chart(profits)

# ================= METRICS =================
st.subheader("📊 Performance Metrics")

m1,m2,m3=st.columns(3)
m1.metric("Peak Profit",round(peak_profit,2))
m2.metric("Max Drawdown",round(max_dd,2))
m3.metric("ROI / 100 rounds",round(roi_100,2))

n1,n2,n3=st.columns(3)
n1.metric("Winrate %",round(winrate*100,2))
n2.metric("Profit Factor",round(profit_factor,2))
n3.metric("Expectancy",round(expectancy,3))

k1,k2=st.columns(2)
k1.metric("Max Loss Streak",max_loss_streak)
k2.metric("Total Trades",total_trades)

# ================= HISTORY =================
st.subheader("History")
hist=pd.DataFrame(engine)
st.dataframe(hist.iloc[::-1],use_container_width=True)
