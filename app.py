import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOCK_BASE = 15
AUTO_REFRESH = 5

st.set_page_config(layout="wide")

# ---------------- CORE ---------------- #

def get_group(n):
    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4
    return None

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

def volatility(data):
    if len(data)<26: return 0.5
    r=data[-26:]
    c=sum(1 for i in range(1,26)
          if r[i]["group"]!=r[i-1]["group"])
    return c/25

def score(data,w):
    h=hits_26(data,w)
    s=streak(data,w)
    if h<6 or s<2:
        return 0
    return (h*1.4)+(s*3)

def scan(data):
    vol=volatility(data)
    if vol>0.65:
        return []
    res=[]
    for w in range(6,20):
        sc=score(data,w)
        if sc>0:
            res.append((w,sc))
    res.sort(key=lambda x:x[1],reverse=True)
    return res[:3]

# ---------------- LOAD ---------------- #

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df=load()
if df.empty:
    st.stop()

numbers=df["number"].dropna().astype(int).tolist()

# ---------------- ENGINE ---------------- #

engine=[]
lock_window=None
lock_remaining=0
miss_streak=0

for i,n in enumerate(numbers):

    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"

    if lock_window:

        state="LOCK"

        if len(engine)>=lock_window:
            predicted=engine[-lock_window]["group"]
            hit=1 if predicted==g else 0

            if hit==0:
                miss_streak+=1
            else:
                miss_streak=0

        lock_remaining-=1

        if miss_streak>=3:
            lock_window=None

        if lock_remaining<=0:
            lock_window=None

    if not lock_window and len(engine)>=26:

        top=scan(engine)

        if top:

            total=sum(sc for w,sc in top)
            confidence=(top[0][1]/total)*100
            p=confidence/100
            ev=(p)-(1-p)

            # Monte Carlo quick test
            arr=np.random.binomial(1,0.25,1000)
            mc_equity=arr.sum()- (1000-arr.sum())
            live_equity=sum(1 if x["hit"]==1 else -1
                            for x in engine
                            if x["hit"] is not None)
            percentile=(mc_equity<live_equity)

            if ev>0 and confidence>=60:

                best_w=top[0][0]
                lock_window=best_w

                lock_remaining=int(LOCK_BASE+confidence/10)
                state="LOCK_START"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":lock_window,
        "state":state
    })

# ---------------- DASHBOARD ---------------- #

st.title("FINAL PRO STABLE ENGINE")

st.metric("Total Rounds",len(engine))
st.metric("Active Window",lock_window)
st.metric("Lock Remaining",lock_remaining)
st.metric("Miss Streak",miss_streak)

# NEXT GROUP
if lock_window and len(engine)>=lock_window:
    next_group=engine[-lock_window]["group"]
    st.markdown(f"""
    <div style='padding:15px;
                background:#1f4e79;
                color:white;
                border-radius:10px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
        NEXT GROUP: {next_group}
    </div>
    """,unsafe_allow_html=True)
else:
    st.warning("NO TRADE ZONE")

# HISTORY
df_engine=pd.DataFrame(engine)
st.dataframe(df_engine.iloc[::-1],use_container_width=True)
