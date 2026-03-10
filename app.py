import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,15]

st.set_page_config(layout="wide")

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine=[]
total_profit=0
last_trade_round=-999
next_signal=None
confidence=0
last_hit=None
last_pred=None
last_ev=0

def window_engine(engine):
    best=None; best_ev=-999; best_wr=0
    for w in WINDOWS:
        hits=[]
        start=max(w,len(engine)-24)   # TURBO lookback ngắn
        for j in range(start,len(engine)):
            if j>=w:
                hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)
        if len(hits)>=18:
            wr=np.mean(hits)
            ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
            if ev>best_ev:
                best_ev=ev; best=w; best_wr=wr
    return best,best_wr,best_ev

def momentum_engine(engine):
    if len(engine)<3: return None,0
    seq=[x["group"] for x in engine[-3:]]
    if len(set(seq))==1:
        return seq[-1],0.6   # turbo boost mạnh
    return None,0

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        hit=1 if predicted==g else 0
        total_profit+=WIN_PROFIT if hit else -LOSE_LOSS
        state="TRADE"
        last_trade_round=i
        last_hit=hit
        last_pred=predicted
        next_signal=None

    # ===== DOUBLE PUSH (lệch 1 nhịp) =====
    if last_hit==0 and last_ev>0:
        next_signal=last_pred
        state="RETRY"

    # ===== GENERATE =====
    if len(engine)>=30 and i-last_trade_round>2:
        w,wr,ev=window_engine(engine)
        m_sig,m_conf=momentum_engine(engine)

        votes={}
        if w:
            g1=engine[-w]["group"]
            votes[g1]=votes.get(g1,0)+wr
        if m_sig:
            votes[m_sig]=votes.get(m_sig,0)+m_conf

        if votes:
            best_group=max(votes,key=votes.get)
            conf=votes[best_group]

            if conf>0.25 and ev>-0.05:
                next_signal=best_group
                confidence=conf
                last_ev=ev
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state
    })

# ================= UI =================
st.title("⚡ TURBO AI ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))
hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

if next_signal:
    st.error(f"🚨 NEXT GROUP: {next_signal} | Turbo Confidence {round(confidence*100,1)}%")
else:
    st.info("No signal")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
