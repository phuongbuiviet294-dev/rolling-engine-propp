import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]

# Risk control
STOPLOSS_STREAK = 6
PAUSE_ROUNDS = 12
RISK_DRAWDOWN = 20

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

# ================= CORE SIM =================
def simulate_until_lock(numbers, LOOKBACK, GAP):
    profit = 0
    engine = []
    last_trade = -999
    next_signal = None

    for i,n in enumerate(numbers):
        g = get_group(n)
        hit=None

        if next_signal is not None:
            hit = 1 if next_signal==g else 0
            profit += WIN_PROFIT if hit else -LOSE_LOSS
            last_trade=i
            next_signal=None

        if len(engine)>=40 and i-last_trade>GAP:
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

            if best_w and best_wr>0.29:
                g1=engine[-best_w]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1

        engine.append({"group":g,"profit":profit})

    return profit, engine

# ================= FIND PEAK LOCK =================
best_profit=-999
best_cfg=(26,4)
best_curve=None

for LB in range(18,36):
    for GP in range(3,7):
        p,eng=simulate_until_lock(numbers,LB,GP)
        if p>best_profit:
            best_profit=p
            best_cfg=(LB,GP)
            best_curve=eng

LOCK_LB,LOCK_GP = best_cfg

profits=[x["profit"] for x in best_curve]
peak_profit=max(profits)
lock_index=profits.index(peak_profit)

# ================= TRUE LIVE ENGINE =================
def run_live(numbers, start_index, LOOKBACK, GAP):
    profit=0
    peak=0
    loss_streak=0
    pause=0
    last_trade=-999
    next_signal=None
    trades=[]

    history=[]

    for i in range(start_index,len(numbers)):
        n=numbers[i]
        g=get_group(n)

        state="SCAN"
        hit=None

        # pause mode
        if pause>0:
            pause-=1
            state="PAUSE"
        else:
            if next_signal is not None:
                hit=1 if next_signal==g else 0
                pnl=WIN_PROFIT if hit else -LOSE_LOSS
                profit+=pnl
                peak=max(peak,profit)
                state="TRADE"
                last_trade=i
                next_signal=None

                if hit:
                    loss_streak=0
                else:
                    loss_streak+=1
                    if loss_streak>=STOPLOSS_STREAK:
                        pause=PAUSE_ROUNDS
                        state="STOPLOSS_PAUSE"

            # signal
            if i-last_trade>GAP and i>start_index+40:
                best_ev=-999
                best_w=None
                best_wr=0

                for w in WINDOWS:
                    recent=[]
                    start=max(w,i-LOOKBACK)
                    for j in range(start,i):
                        if j>=w:
                            recent.append(
                                1 if get_group(numbers[j])==get_group(numbers[j-w]) else 0
                            )
                    if len(recent)>=20:
                        wr=np.mean(recent)
                        ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                        if ev>best_ev:
                            best_ev=ev
                            best_w=w
                            best_wr=wr

                if best_w and best_wr>0.29:
                    g1=get_group(numbers[i-best_w])
                    if get_group(numbers[i-1])!=g1:
                        next_signal=g1
                        state="SIGNAL"

        dd=peak-profit
        history.append({
            "round":i+1,
            "group":g,
            "hit":hit,
            "state":state,
            "profit":round(profit,2),
            "drawdown":round(dd,2)
        })

    return profit,peak,history,next_signal

live_profit,peak_profit_live,history,next_signal = run_live(
    numbers, lock_index, LOCK_LB, LOCK_GP
)

# ================= METRICS =================
profits=[h["profit"] for h in history]
peak=max(profits) if profits else 0
dd=max([peak-p for p in profits]) if profits else 0

hits=[h["hit"] for h in history if h["hit"] is not None]
wr=np.mean(hits) if hits else 0

wins=sum(1 for h in hits if h==1)
losses=sum(1 for h in hits if h==0)
pf=(wins*WIN_PROFIT)/(losses*LOSE_LOSS) if losses else 0
exp=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

# ================= UI =================
st.title("🚀 TRUE LIVE TRADING ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Live Profit",round(live_profit,2))
c2.metric("Peak Profit",round(peak,2))
c3.metric("Max Drawdown",round(dd,2))

c4,c5,c6=st.columns(3)
c4.metric("Winrate %",round(wr*100,2))
c5.metric("Profit Factor",round(pf,2))
c6.metric("Expectancy",round(exp,3))

st.caption(f"🔒 Locked @ Round {lock_index+1} | Lookback={LOCK_LB} Gap={LOCK_GP}")

# ================= NEXT SIGNAL =================
if next_signal:
    st.success(f"🎯 NEXT GROUP: {next_signal}")
else:
    st.info("Scanning...")

# ================= HISTORY =================
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(history).iloc[::-1],use_container_width=True)
