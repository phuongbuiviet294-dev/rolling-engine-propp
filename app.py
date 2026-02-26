import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOCK_BASE = 12
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

# ---------------- REBOUND ---------------- #

rebound_memory={"total":0,"win":0}

def rebound_winrate():
    if rebound_memory["total"]==0:
        return 0
    return rebound_memory["win"]/rebound_memory["total"]

def count_rebound_patterns(data,w):

    if len(data)<15: return 0

    vol=volatility(data)
    if vol<0.30 or vol>0.62:
        return 0

    recent=data[-15:]
    seq=[]

    for i in range(len(recent)):
        if i>=w and recent[i]["group"]==recent[i-w]["group"]:
            seq.append(1)
        else:
            seq.append(0)

    count=0

    for i in range(len(seq)-6):
        if seq[i]==1 and seq[i+1]==1:
            for rest in range(2,5):
                if i+2+rest+1 < len(seq):
                    zeros=seq[i+2:i+2+rest]
                    if all(z==0 for z in zeros):
                        if seq[i+2+rest]==1 and seq[i+3+rest]==1:
                            count+=1
    return count

# ---------------- SCORE ---------------- #

def score(data,w):

    h=hits_26(data,w)
    s=streak(data,w)
    vol=volatility(data)

    reb_count=count_rebound_patterns(data,w)
    reb_wr=rebound_winrate()
    reb_total=rebound_memory["total"]

    base=(h*1.4)+(s*3)

    # Trend Mode
    if h>=6 and s>=2 and vol<0.62:
        return base

    # Rebound Learning
    if (
        reb_count>=2 and
        h>=5 and
        0.30<=vol<=0.62 and
        reb_total<10
    ):
        return base*1.15

    # Rebound Confirmed
    if (
        reb_count>=2 and
        h>=5 and
        0.30<=vol<=0.62 and
        reb_total>=10 and
        reb_wr>0.55
    ):
        return base*1.25

    return 0

def scan(data):

    vol=volatility(data)
    if vol>0.62:
        return []

    res=[]
    for w in range(6,20):
        sc=score(data,w)
        if sc>0:
            res.append((w,sc))

    res.sort(key=lambda x:x[1],reverse=True)

    # Spread filter
    if len(res)>1:
        if res[0][1]-res[1][1] < 3:
            return []

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

            best_w=top[0][0]
            reb_count=count_rebound_patterns(engine,best_w)
            reb_wr=rebound_winrate()
            reb_total=rebound_memory["total"]
            vol=volatility(engine)

            # Trend Lock
            if ev>0 and confidence>=60 and vol<0.62:

                lock_window=best_w
                lock_remaining=int(LOCK_BASE+confidence/12)
                state="LOCK_START"

            # Rebound Lock
            elif (
                reb_count>=2 and
                confidence>=50 and
                0.30<=vol<=0.62 and
                (
                    reb_total<10 or
                    (reb_total>=10 and reb_wr>0.55)
                )
            ):
                lock_window=best_w
                lock_remaining=10
                state="REBOUND_CONFIRMED"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":lock_window,
        "state":state
    })

    if hit is not None and state=="REBOUND_CONFIRMED":
        rebound_memory["total"]+=1
        if hit==1:
            rebound_memory["win"]+=1

# ---------------- DASHBOARD ---------------- #

st.title("FINAL OPTIMIZED ENGINE")

st.metric("Total Rounds",len(engine))
st.metric("Active Window",lock_window)
st.metric("Lock Remaining",lock_remaining)
st.metric("Miss Streak",miss_streak)
st.metric("Rebound WR",round(rebound_winrate()*100,2))

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

df_engine=pd.DataFrame(engine)
st.dataframe(df_engine.iloc[::-1],use_container_width=True)
