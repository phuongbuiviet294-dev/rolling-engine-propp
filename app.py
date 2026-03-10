import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(8,18)
BASE_LOOKBACK = 30
MIN_SAMPLE = 20
BASE_GAP = 4
DD_LIMIT = 5

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
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine=[]
equity=[]
total_profit=0
last_trade_round=-999
loss_streak=0

next_signal=None
next_window=None
next_wr=None
next_ev=None
regime="—"

def detect_regime(vol):
    if vol < 0.12: return "🚀 TREND"
    if vol < 0.20: return "🌊 SIDEWAY"
    return "🌪 CHAOS"

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    wr_used=None
    ev_used=None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        wr_used=next_wr
        ev_used=next_ev

        hit=1 if predicted==g else 0

        if hit:
            total_profit+=WIN_PROFIT
            loss_streak=0
        else:
            total_profit-=LOSE_LOSS
            loss_streak+=1

        state="TRADE"
        last_trade_round=i
        next_signal=None

    equity.append(total_profit)

    # ===== ADAPTIVE LOOKBACK =====
    if len(engine)>50:
        recent=[x["hit"] for x in engine[-30:] if x["hit"] is not None]
        vol=np.std(recent) if recent else 0.2
        LOOKBACK=int(BASE_LOOKBACK*(1+vol))
        GAP=int(BASE_GAP*(1+vol))
    else:
        LOOKBACK=BASE_LOOKBACK
        GAP=BASE_GAP
        vol=0.2

    regime=detect_regime(vol)

    # ===== SIGNAL ENGINE =====
    if len(engine)>=40 and i-last_trade_round>GAP and loss_streak<DD_LIMIT and regime!="🌪 CHAOS":

        scores=[]

        for w in WINDOW_RANGE:
            hits=[]
            start=max(w,len(engine)-LOOKBACK)

            for j in range(start,len(engine)):
                if j>=w:
                    hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)

            if len(hits)>=MIN_SAMPLE:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                vol_w=np.std(hits)
                scores.append((w,wr,ev,vol_w))

        if scores:
            best_ev=max(scores,key=lambda x:x[2])
            best_wr=max(scores,key=lambda x:x[1])
            best_stable=min(scores,key=lambda x:x[3])

            # ===== Ensemble Vote =====
            votes=[]
            for w,wr,ev,vol_w in [best_ev,best_wr,best_stable]:
                votes.append(engine[-w]["group"])

            vote=max(set(votes),key=votes.count)

            if engine[-1]["group"]!=vote:
                next_signal=vote
                next_window=best_ev[0]
                next_wr=best_ev[1]
                next_ev=best_ev[2]
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":wr_used,
        "ev":ev_used,
        "state":state
    })

# ================= DASHBOARD =================
st.title("🚀 ULTRA PRO MAX — LIVE ADAPTIVE AI")

c1,c2,c3,c4=st.columns(4)
c1.metric("Total Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))
c4.metric("Market Regime",regime)

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:22px;background:#c62828;color:white;
                border-radius:14px;text-align:center;
                font-size:30px;font-weight:bold'>
        🎯 NEXT GROUP: {next_signal}
        <br>Window: {next_window}
        <br>WR: {round(next_wr*100,2)}%
        <br>EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("No valid signal")

# ================= EQUITY CURVE =================
st.subheader("Profit Curve")
st.line_chart(equity)

# ================= HISTORY =================
st.subheader("History")
hist_df=pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df,use_container_width=True)
