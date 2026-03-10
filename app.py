import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

LIVE_RECENT_ROUNDS = 400
WINDOWS = [6,9,12,15,18]

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

numbers_all = df["number"].dropna().astype(int).tolist()
numbers = numbers_all[-LIVE_RECENT_ROUNDS:]

# ================= HELPERS =================
def window_engine(engine, LOOKBACK):
    best=None; best_ev=-999; best_wr=0
    for w in WINDOWS:
        hits=[]
        start=max(w,len(engine)-LOOKBACK)
        for j in range(start,len(engine)):
            if j>=w:
                hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)
        if len(hits)>=20:
            wr=np.mean(hits)
            ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
            if ev>best_ev:
                best_ev=ev; best=w; best_wr=wr
    return best,best_wr,best_ev

def momentum_engine(engine):
    if len(engine)<8: return None,0
    seq=[x["group"] for x in engine[-4:]]
    if len(set(seq))==1:
        return seq[-1],0.6
    return None,0

def revert_engine(engine):
    if len(engine)<10: return None,0
    last=engine[-1]["group"]
    counts=[x["group"] for x in engine[-10:]].count(last)
    if counts>=6:
        return (last%4)+1,0.55
    return None,0

# ================= ENGINE =================
engine=[]
total_profit=0
last_trade_round=-999
next_signal=None
confidence=0
cooldown_until=-1

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
        next_signal=None

    allow=True
    if i<cooldown_until: allow=False

    # ===== REGIME =====
    recent=[x["group"] for x in engine[-30:]]
    regime_score=1
    if len(recent)>=30:
        changes=sum(a!=b for a,b in zip(recent,recent[1:]))
        if changes>22:
            regime_score=0.5
            allow=False

    # ===== ENSEMBLE =====
    if allow and len(engine)>=40 and i-last_trade_round>4:
        w,wr,ev=window_engine(engine,30)
        m_sig,m_conf=momentum_engine(engine)
        r_sig,r_conf=revert_engine(engine)

        votes={}
        if w:
            g1=engine[-w]["group"]
            votes[g1]=votes.get(g1,0)+wr
        if m_sig:
            votes[m_sig]=votes.get(m_sig,0)+m_conf
        if r_sig:
            votes[r_sig]=votes.get(r_sig,0)+r_conf

        if votes:
            best_group=max(votes,key=votes.get)
            conf=votes[best_group]*regime_score

            if conf>0.55 and ev>0:
                next_signal=best_group
                confidence=conf
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
st.title("🧠 LIVE PRO MAX ELITE — ENSEMBLE AI")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))
hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

if next_signal:
    st.success(f"🎯 NEXT GROUP: {next_signal} | Confidence: {round(confidence*100,1)}%")
else:
    st.info("No valid signal")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
