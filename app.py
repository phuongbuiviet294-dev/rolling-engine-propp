import streamlit as st
import pandas as pd
import numpy as np
import random

# ================= CONFIG ================= #

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
BASE_LOCK = 18

st.set_page_config(layout="wide")

# ================= CORE ================= #

def get_group(n):
    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4
    return None

def volatility(engine):
    if len(engine)<26: return 0.5
    r=engine[-26:]
    return sum(1 for i in range(1,26)
               if r[i]["group"]!=r[i-1]["group"])/25

def detect_regime(vol, history):
    if len(history)<100:
        return "HIGH_VOL"
    mean=np.mean(history[-100:])
    std=np.std(history[-100:])
    if std==0:
        return "HIGH_VOL"
    z=(vol-mean)/std
    if z<-0.5:
        return "STABLE"
    elif z<=0.8:
        return "HIGH_VOL"
    else:
        return "CHAOS"

def hits_26(data,w):
    if len(data)<26: return 0
    r=data[-26:]
    return sum(1 for i in range(w,26)
               if r[i]["group"]==r[i-w]["group"])

def streak(data,w):
    s=0
    i=len(data)-1
    while i-w>=0:
        if data[i]["group"]==data[i-w]["group"]:
            s+=1
            i-=1
        else:
            break
    return s

def scan(data):
    res=[]
    for w in range(6,20):
        sc=hits_26(data,w)*1.5+streak(data,w)*3
        if sc>0:
            res.append((w,sc))
    res.sort(key=lambda x:x[1],reverse=True)
    return res[:3]

def trend_predict(engine):
    top=scan(engine)
    if not top:
        return None,None
    votes={}
    for w,sc in top:
        if len(engine)>=w:
            g=engine[-w]["group"]
            votes[g]=votes.get(g,0)+sc
    best=max(votes,key=votes.get)
    for w,sc in top:
        if len(engine)>=w and engine[-w]["group"]==best:
            return best,w
    return None,None

def anti_predict(engine):
    if len(engine)<2:
        return None
    last=engine[-1]["group"]
    candidates=[1,2,3,4]
    candidates.remove(last)
    r=engine[-26:]
    freq={g:sum(1 for e in r if e["group"]==g) for g in candidates}
    return max(freq,key=freq.get)

def bayes_wr(engine,n=40):
    recent=[e["hit"] for e in engine[-n:] if e["hit"] is not None]
    if not recent:
        return 0.5
    wins=sum(recent)
    trades=len(recent)
    return (wins+1)/(trades+2)

def adaptive_kelly(p,dd):
    k=(2*p-1)*0.4
    k=min(0.25,max(0.05,k))
    if dd>0.25:
        return 0
    if dd>0.15:
        return k*0.5
    return k

# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df=load()
if df.empty:
    st.stop()

numbers=df["number"].dropna().astype(int).tolist()

# ================= ENGINE ================= #

engine=[]
vol_history=[]
equity=1
peak=1
drawdown=0
lock=None
lock_remaining=0
miss_streak=0
pause=0

for i,n in enumerate(numbers):

    g=get_group(n)
    vol=volatility(engine)
    vol_history.append(vol)
    regime=detect_regime(vol,vol_history)

    predicted=None
    hit=None
    state="SCAN"

    if pause>0:
        pause-=1

    elif lock:

        state="LOCK"

        # ===== FIXED SECTION =====
        if lock=="ANTI":
            predicted=anti_predict(engine)

        elif isinstance(lock,int):
            if len(engine)>=lock:
                predicted=engine[-lock]["group"]
            else:
                predicted=None

        else:
            predicted=None
        # =========================

        if predicted is not None:
            hit=1 if predicted==g else 0

            if hit==0:
                miss_streak+=1
            else:
                miss_streak=0

            p=bayes_wr(engine)
            k=adaptive_kelly(p,drawdown)

            if hit==1:
                equity*=1+k
            else:
                equity*=1-k

            peak=max(peak,equity)
            drawdown=(peak-equity)/peak

        lock_remaining-=1

        if miss_streak>=2:
            lock=None

        if lock_remaining<=0:
            lock=None

    # ===== START NEW LOCK =====
    if not lock and pause==0 and len(engine)>=20:

        if regime=="STABLE":
            pred,w=trend_predict(engine)
            if pred:
                lock=w
                lock_remaining=BASE_LOCK
                state="LOCK_START"

        elif regime=="HIGH_VOL":
            lock="ANTI"
            lock_remaining=8
            state="ANTI_START"

    # ===== FINAL DEFENSE =====
    if drawdown>0.35:
        pause=10
        lock=None

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "regime":regime,
        "equity":round(equity,4)
    })

# ================= DASHBOARD ================= #

st.title("🏛 PRO COMPLETE AI ENGINE")

col1,col2,col3,col4=st.columns(4)
col1.metric("Equity",round(equity,2))
col2.metric("Drawdown %",round(drawdown*100,2))
col3.metric("Regime",engine[-1]["regime"])
col4.metric("Active Lock",lock)

if engine[-1]["predicted"]:
    st.success(f"🎯 NEXT GROUP: {engine[-1]['predicted']}")
else:
    st.warning("NO TRADE")

st.line_chart([e["equity"] for e in engine])

st.subheader("History (Newest First)")
df_engine=pd.DataFrame(engine)
st.dataframe(df_engine.iloc[::-1],use_container_width=True)

st.caption("PRO COMPLETE VERSION | Stable | No ANTI crash | Kelly | Drawdown Guard")
