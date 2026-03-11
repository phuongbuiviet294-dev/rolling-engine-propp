import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,15]

# ===== RISK GUARD =====
LOSS_SOFT = 3
LOSS_HARD = 5
LOSS_KILL = 8

COOLDOWN_SOFT = 0
COOLDOWN_HARD = 3
COOLDOWN_KILL = 10

DD_LIMIT = 10
DD_WINDOW = 50
DD_COOLDOWN = 20

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
def simulate(numbers, LOOKBACK, GAP):
    engine=[]
    total_profit=0
    peak_profit=0
    last_trade_round=-999
    next_signal=None

    loss_streak=0
    cooldown=0

    for i,n in enumerate(numbers):
        g=get_group(n)

        predicted=None
        hit=None
        state="SCAN"

        # ===== COOLDOWN =====
        if cooldown>0:
            cooldown-=1
            state="COOLDOWN"
            engine.append({
                "round":i+1,
                "group":g,
                "hit":None,
                "state":state,
                "profit":round(total_profit,2)
            })
            continue

        # ===== EXECUTE TRADE =====
        if next_signal is not None:
            predicted=next_signal
            hit=1 if predicted==g else 0

            bet_win=WIN_PROFIT
            bet_loss=LOSE_LOSS

            # soft reduce bet
            if loss_streak>=LOSS_SOFT:
                bet_win*=0.5
                bet_loss*=0.5

            pnl = bet_win if hit else -bet_loss
            total_profit += pnl
            peak_profit=max(peak_profit,total_profit)

            state="TRADE"
            last_trade_round=i
            next_signal=None

            if hit:
                loss_streak=0
            else:
                loss_streak+=1

        # ===== LOSS STREAK GUARD =====
        if loss_streak>=LOSS_KILL:
            cooldown=COOLDOWN_KILL
        elif loss_streak>=LOSS_HARD:
            cooldown=COOLDOWN_HARD

        # ===== DRAWDOWN GUARD =====
        if len(engine)>DD_WINDOW:
            recent=engine[-DD_WINDOW:]
            p0=recent[0]["profit"]
            if peak_profit-total_profit>=DD_LIMIT and total_profit<p0:
                cooldown=DD_COOLDOWN

        # ===== GENERATE SIGNAL =====
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
            "profit":round(total_profit,2)
        })

    return engine,next_signal

# ================= LOCK CONFIG =================
best_profit=-999
best_cfg=(26,4)

for LB in range(18,31):
    for GP in range(3,7):
        eng,_=simulate(numbers,LB,GP)
        p=eng[-1]["profit"]
        if p>best_profit:
            best_profit=p
            best_cfg=(LB,GP)

LOCK_LB,LOCK_GP=best_cfg
engine,next_signal=simulate(numbers,LOCK_LB,LOCK_GP)

# ================= STATS =================
profits=[x["profit"] for x in engine]
peak=max(profits)
dd=max(peak-p for p in profits)

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0

# ================= UI =================
st.title("🧠 SMART RISK GUARD — BALANCED")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(engine[-1]["profit"],2))
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Lookback={LOCK_LB} | Gap={LOCK_GP} | Risk Guard ON")

if next_signal:
    st.success(f"🎯 NEXT GROUP: {next_signal}")
else:
    st.info("Scanning...")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
