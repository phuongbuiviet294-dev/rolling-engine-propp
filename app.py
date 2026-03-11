import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOW = 9

# ----- NORMAL MODE -----
N_LOOKBACK = 26
N_GAP = 4
N_WR_TH = 0.29
N_EV_TH = 0
N_MIN_SAMPLES = 20
N_MAX_LOSS_STREAK = 5
N_COOLDOWN = 3

# ----- TURBO MODE -----
T_LOOKBACK = 24
T_GAP = 3
T_WR_TH = 0.27
T_EV_TH = -0.02
T_MIN_SAMPLES = 14
T_MAX_LOSS_STREAK = 6
T_COOLDOWN = 2

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
if "number" not in df.columns:
    st.error("Missing column: number")
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
def run_engine():
    engine=[]
    total_profit=0
    peak_profit=0
    max_dd=0

    last_trade_round=-999
    cooldown_until=-1
    loss_streak=0

    next_signal=None
    next_ev=None
    next_wr=None

    mode="NORMAL"

    for i,n in enumerate(numbers):
        g=get_group(n)
        predicted=None
        hit=None
        state="SCAN"

        # ===== EXECUTE TRADE =====
        if next_signal is not None:
            predicted=next_signal
            hit=1 if predicted==g else 0
            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += pnl
            state="TRADE"
            last_trade_round=i
            next_signal=None

            if hit:
                loss_streak=0
            else:
                loss_streak+=1

        # ===== UPDATE STATS =====
        peak_profit=max(peak_profit,total_profit)
        dd=peak_profit-total_profit
        max_dd=max(max_dd,dd)

        # ===== MODE SWITCH =====
        recent_hits=[x["hit"] for x in engine[-25:] if x["hit"] is not None]
        if len(recent_hits)>=15:
            wr25=np.mean(recent_hits)
            recent_profit=total_profit-(engine[-120]["profit"] if len(engine)>120 else 0)

            if wr25>=0.48 or recent_profit>0:
                mode="TURBO"
            elif wr25<0.42 or dd>12:
                mode="NORMAL"

        if mode=="TURBO":
            LOOKBACK=T_LOOKBACK
            GAP=T_GAP
            WR_TH=T_WR_TH
            EV_TH=T_EV_TH
            MIN_SAMPLES=T_MIN_SAMPLES
            MAX_LOSS=T_MAX_LOSS_STREAK
            COOLDOWN=T_COOLDOWN
        else:
            LOOKBACK=N_LOOKBACK
            GAP=N_GAP
            WR_TH=N_WR_TH
            EV_TH=N_EV_TH
            MIN_SAMPLES=N_MIN_SAMPLES
            MAX_LOSS=N_MAX_LOSS_STREAK
            COOLDOWN=N_COOLDOWN

        # ===== STOPLOSS GUARD =====
        if loss_streak>=MAX_LOSS:
            cooldown_until=i+COOLDOWN
            loss_streak=0

        # ===== GENERATE SIGNAL =====
        if (
            len(engine)>=40 and
            i-last_trade_round>GAP and
            i>cooldown_until
        ):
            recent=[]
            start=max(WINDOW,len(engine)-LOOKBACK)

            for j in range(start,len(engine)):
                if j>=WINDOW:
                    recent.append(
                        1 if engine[j]["group"]==engine[j-WINDOW]["group"] else 0
                    )

            if len(recent)>=MIN_SAMPLES:
                wr=np.mean(recent)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

                if wr>WR_TH and ev>EV_TH:
                    g1=engine[-WINDOW]["group"]
                    if engine[-1]["group"]!=g1:
                        next_signal=g1
                        next_wr=wr
                        next_ev=ev
                        state="SIGNAL"

        engine.append({
            "round":i+1,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":round(total_profit,2),
            "mode":mode
        })

    # ===== METRICS =====
    trades=[x for x in engine if x["hit"] is not None]
    wins=[x for x in trades if x["hit"]==1]
    losses=[x for x in trades if x["hit"]==0]

    winrate=len(wins)/len(trades) if trades else 0
    profit_factor=(
        sum(WIN_PROFIT for _ in wins) /
        abs(sum(-LOSE_LOSS for _ in losses))
        if losses else 0
    )
    expectancy=total_profit/len(trades) if trades else 0
    roi100=total_profit/len(engine)*100 if engine else 0

    # loss streak
    cur_ls=0
    max_ls=0
    for x in trades:
        if x["hit"]==0:
            cur_ls+=1
            max_ls=max(max_ls,cur_ls)
        else:
            cur_ls=0

    return engine,total_profit,peak_profit,max_dd,winrate,profit_factor,expectancy,roi100,max_ls,next_signal,next_wr,next_ev

engine,total_profit,peak_profit,max_dd,wr,pf,exp,roi100,max_ls,next_signal,next_wr,next_ev=run_engine()

# ================= UI =================
st.title("🚀 TURBO ADAPTIVE PRO ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))
c3.metric("Winrate %",round(wr*100,2))

c4,c5,c6=st.columns(3)
c4.metric("Peak Profit",round(peak_profit,2))
c5.metric("Max Drawdown",round(max_dd,2))
c6.metric("ROI / 100 rounds",round(roi100,2))

c7,c8,c9=st.columns(3)
c7.metric("Profit Factor",round(pf,2))
c8.metric("Expectancy",round(exp,3))
c9.metric("Max Loss Streak",max_ls)

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:18px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
        🚨 READY TO BET 🚨<br>
        🎯 NEXT GROUP: {next_signal}<br>
        WR: {round(next_wr*100,2)}% | EV: {round(next_ev,3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

# ================= HISTORY =================
st.subheader("History")
hist=pd.DataFrame(engine)
st.dataframe(hist.iloc[::-1],use_container_width=True)
