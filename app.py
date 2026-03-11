import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,15]

STOPLOSS_STREAK = 4
COOLDOWN_ROUNDS = 6

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

df=load()
numbers=df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
def simulate(nums,LOOKBACK,GAP):
    engine=[]
    total_profit=0
    last_trade=-999
    next_signal=None
    loss_streak=0
    cooldown=0

    for i,n in enumerate(nums):
        g=get_group(n)
        hit=None
        state="SCAN"

        # ===== EXECUTE =====
        if next_signal is not None:
            hit=1 if next_signal==g else 0
            pnl=WIN_PROFIT if hit else -LOSE_LOSS
            total_profit+=pnl
            state="TRADE"
            last_trade=i
            next_signal=None

            if hit:
                loss_streak=0
            else:
                loss_streak+=1
                if loss_streak>=STOPLOSS_STREAK:
                    cooldown=COOLDOWN_ROUNDS

        # ===== COOLDOWN =====
        if cooldown>0:
            cooldown-=1
            engine.append({
                "round":i+1,
                "group":g,
                "hit":hit,
                "state":"COOLDOWN",
                "profit":round(total_profit,2)
            })
            continue

        # ===== TREND CHECK =====
        recent_hits=[x["hit"] for x in engine[-20:] if x["hit"] is not None]
        short_wr=np.mean(recent_hits) if len(recent_hits)>=10 else 0.5

        # ===== GENERATE SIGNAL =====
        if len(engine)>=40 and i-last_trade>GAP and short_wr>0.48:
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
                if len(recent)>=15:
                    wr=np.mean(recent)
                    ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                    if ev>best_ev:
                        best_ev=ev
                        best_w=w
                        best_wr=wr

            if best_w and best_wr>0.27 and best_ev>0:
                g1=engine[-best_w]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    state="SIGNAL"

        engine.append({
            "round":i+1,
            "group":g,
            "hit":hit,
            "state":state,
            "profit":round(total_profit,2)
        })

    return engine,total_profit,next_signal

# ================= FIND PEAK LOCK =================
eng_full,_,_=simulate(numbers,26,3)
profits=[x["profit"] for x in eng_full]
peak_idx=int(np.argmax(profits))
peak_profit=max(profits)

# chỉ dùng dữ liệu trước đỉnh
train_numbers=numbers[:peak_idx]

# ================= OPTIMIZE ON PAST =================
best_profit=-999
best_cfg=(26,3)

for LB in range(18,29):
    for GP in range(3,7):
        _,p,_=simulate(train_numbers,LB,GP)
        if p>best_profit:
            best_profit=p
            best_cfg=(LB,GP)

LOCK_LB,LOCK_GP=best_cfg

# ================= LIVE RUN =================
engine,profit,next_signal=simulate(numbers,LOCK_LB,LOCK_GP)

# ================= UI =================
st.title("🚀 TRUE LOCK PRO ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Live Profit",engine[-1]["profit"])

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"LOCKED @ Peak Round {peak_idx} | Lookback={LOCK_LB} Gap={LOCK_GP}")

if next_signal:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;
                text-align:center;font-size:28px;font-weight:bold'>
        🚨 READY TO BET 🚨<br>
        🎯 NEXT GROUP: {next_signal}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning...")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
