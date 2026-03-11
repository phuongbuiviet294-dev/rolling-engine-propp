import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,15]

st.set_page_config(layout="wide")

# ================= LOAD =================
@st.cache_data(ttl=AUTO_REFRESH)
def load():
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns=[c.strip().lower() for c in df.columns]
    return df

df=load()
numbers=df["number"].dropna().astype(int).tolist()

# ================= GROUP =================
def get_group(n):
    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4
    return None

# ================= ENGINE =================
def run_engine(numbers,LOOKBACK=26,GAP=4):
    engine=[]
    total_profit=0
    peak=0
    max_dd=0
    last_trade=-999
    next_signal=None
    loss_streak=0
    max_loss_streak=0
    win_streak=0
    max_win_streak=0

    for i,n in enumerate(numbers):
        g=get_group(n)
        predicted=None
        hit=None
        state="SCAN"

        if next_signal is not None:
            predicted=next_signal
            hit=1 if predicted==g else 0
            pnl=WIN_PROFIT if hit else -LOSE_LOSS
            total_profit+=pnl
            peak=max(peak,total_profit)
            dd=peak-total_profit
            max_dd=max(max_dd,dd)
            state="TRADE"
            last_trade=i
            next_signal=None

            if hit:
                win_streak+=1
                loss_streak=0
                max_win_streak=max(max_win_streak,win_streak)
            else:
                loss_streak+=1
                win_streak=0
                max_loss_streak=max(max_loss_streak,loss_streak)

        if len(engine)>=40 and i-last_trade>GAP:
            best_ev=-999
            best_w=None
            best_wr=0
            for w in WINDOWS:
                recent=[]
                start=max(w,len(engine)-LOOKBACK)
                for j in range(start,len(engine)):
                    if j>=w:
                        recent.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)
                if len(recent)>=20:
                    wr=np.mean(recent)
                    ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                    if ev>best_ev:
                        best_ev=ev
                        best_w=w
                        best_wr=wr
            if best_w and best_wr>0.3 and best_ev>0:
                g1=engine[-best_w]["group"]
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
            "profit":total_profit,
            "drawdown":peak-total_profit,
            "win_streak":win_streak,
            "loss_streak":loss_streak
        })

    return pd.DataFrame(engine),peak,max_dd,max_win_streak,max_loss_streak

# ================= RUN =================
hist,peak,max_dd,max_win_streak,max_loss_streak=run_engine(numbers)

# ================= METRICS =================
hits=hist["hit"].dropna()
wr=hits.mean() if len(hits)>0 else 0
profit=hist["profit"].iloc[-1]
total_trades=len(hits)
roi_100=profit/len(hist)*100 if len(hist)>0 else 0

gross_win=(hits==1).sum()*WIN_PROFIT
gross_loss=(hits==0).sum()*LOSE_LOSS
pf=gross_win/gross_loss if gross_loss>0 else 0
expectancy=(wr*WIN_PROFIT)-(1-wr)*LOSE_LOSS

# ================= UI =================
st.title("🧠 PRO ANALYTICS — LIGHT VERSION")

c1,c2,c3,c4=st.columns(4)
c1.metric("Profit",round(profit,2))
c2.metric("Peak Profit",round(peak,2))
c3.metric("Max Drawdown",round(max_dd,2))
c4.metric("Winrate %",round(wr*100,2))

c5,c6,c7,c8=st.columns(4)
c5.metric("Profit Factor",round(pf,2))
c6.metric("Expectancy",round(expectancy,3))
c7.metric("ROI / 100 rounds",round(roi_100,2))
c8.metric("Total Trades",total_trades)

c9,c10=st.columns(2)
c9.metric("Max Win Streak",max_win_streak)
c10.metric("Max Loss Streak",max_loss_streak)

st.divider()

# ================= STATE STATS =================
st.subheader("⚙️ State Breakdown")
state_counts=hist["state"].value_counts()
st.dataframe(state_counts)

# ================= HISTORY =================
st.subheader("📜 Full History")
st.dataframe(hist.iloc[::-1],use_container_width=True)
