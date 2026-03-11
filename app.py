import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9,15]
LOOKBACK_RANGE = range(18,41)
GAP_RANGE = range(2,7)

LOCK_ROUND = 3662   # ✅ mốc khóa thực chiến

STOPLOSS_STREAK = 5
PAUSE_AFTER_SL = 3

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
    df.columns=[c.strip().lower() for c in df.columns]
    return df

df = load()
numbers = df["number"].dropna().astype(int).tolist()

# ================= CORE ENGINE =================
def simulate(numbers, LOOKBACK, GAP, WINDOW):
    total_profit = 0
    engine=[]
    next_signal=None
    last_trade_round=-999
    loss_streak=0
    pause=0

    for i,n in enumerate(numbers):
        g=get_group(n)

        predicted=None
        hit=None
        state="SCAN"

        # ===== STOPLOSS PAUSE =====
        if pause>0:
            state="PAUSE"
            pause-=1
        else:

            # ===== EXECUTE =====
            if next_signal is not None:
                predicted=next_signal
                hit=1 if predicted==g else 0
                total_profit += WIN_PROFIT if hit else -LOSE_LOSS
                state="TRADE"
                last_trade_round=i
                next_signal=None

                if hit==0:
                    loss_streak+=1
                    if loss_streak>=STOPLOSS_STREAK:
                        state="STOPLOSS"
                        pause=PAUSE_AFTER_SL
                        loss_streak=0
                else:
                    loss_streak=0

            # ===== SIGNAL =====
            if len(engine)>=40 and i-last_trade_round>GAP:
                recent=[]
                start=max(WINDOW,len(engine)-LOOKBACK)
                for j in range(start,len(engine)):
                    if j>=WINDOW:
                        recent.append(
                            1 if engine[j]["group"]==engine[j-WINDOW]["group"] else 0
                        )
                if len(recent)>=20:
                    wr=np.mean(recent)
                    ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                    if wr>0.30 and ev>0:
                        g1=engine[-WINDOW]["group"]
                        if engine[-1]["group"]!=g1:
                            next_signal=g1
                            state="SIGNAL"

        engine.append({
            "round":i+1,
            "number":n,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":round(total_profit,2)
        })

    return total_profit,engine,next_signal

# ================= BACKTEST → FIND BEST CONFIG =================
best_profit=-999
best_cfg=(26,4,9)

train_numbers = numbers[:LOCK_ROUND]

for LB in LOOKBACK_RANGE:
    for GP in GAP_RANGE:
        for W in WINDOWS:
            p,_,_=simulate(train_numbers,LB,GP,W)
            if p>best_profit:
                best_profit=p
                best_cfg=(LB,GP,W)

LOCK_LB,LOCK_GP,LOCK_W = best_cfg

# ================= LIVE SIMULATION =================
live_numbers = numbers[LOCK_ROUND:]

live_profit,live_engine,next_signal = simulate(
    live_numbers,LOCK_LB,LOCK_GP,LOCK_W
)

# ================= METRICS =================
hits=[x["hit"] for x in live_engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0

profits=[x["profit"] for x in live_engine]
peak=max(profits) if profits else 0
dd=peak-profits[-1] if profits else 0

wins=[WIN_PROFIT for x in hits if x==1]
losses=[LOSE_LOSS for x in hits if x==0]

pf=sum(wins)/sum(losses) if losses else 0
exp=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

# ================= UI =================
st.title("🚀 LIVE TRADING ENGINE — NO REPAINT")

c1,c2,c3=st.columns(3)
c1.metric("Live Rounds",len(live_engine))
c2.metric("Live Profit",round(profits[-1],2))
c3.metric("Live Winrate %",round(wr*100,2))

c4,c5,c6=st.columns(3)
c4.metric("Peak Profit",round(peak,2))
c5.metric("Drawdown",round(dd,2))
c6.metric("Profit Factor",round(pf,2))

c7,c8=st.columns(2)
c7.metric("Expectancy",round(exp,3))
c8.metric("Total Trades",len(hits))

st.caption(f"🔒 LOCKED @ Round {LOCK_ROUND} → Lookback={LOCK_LB} | Gap={LOCK_GP} | Window={LOCK_W}")

# ================= NEXT SIGNAL =================
if next_signal:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;font-size:28px;font-weight:bold'>
        🚨 LIVE SIGNAL 🚨<br>
        🎯 NEXT GROUP: {next_signal}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning live...")

# ================= HISTORY =================
st.subheader("Live History (No Repaint)")
hist=pd.DataFrame(live_engine)
st.dataframe(hist.iloc[::-1],use_container_width=True)
