import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

BASE_LOCK = 18
AUTO_REFRESH = 5
ALLOWED_WINDOWS = [9, 14]

WIN_PROFIT = 2.5
LOSE_LOSS = 1

st.set_page_config(layout="wide")

# ================= CORE ================= #

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

def recent_winrate(engine, w, lookback=50):
    df = pd.DataFrame(engine)
    df_w = df[(df["window"]==w) & (df["hit"].notna())]
    if len(df_w) == 0:
        return 0
    return df_w.tail(lookback)["hit"].mean()

def adaptive_lock(engine):
    df = pd.DataFrame(engine)
    df_hits = df[df["hit"].notna()].tail(20)

    if len(df_hits) < 10:
        return BASE_LOCK

    p = df_hits["hit"].mean()
    vol = (p*(1-p))**0.5

    if vol > 0.49:
        return 6
    elif vol > 0.47:
        return 10
    elif vol > 0.45:
        return 15
    else:
        return BASE_LOCK

# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

engine=[]
lock_window=None
lock_remaining=0
miss_streak=0
total_profit=0
equity_curve=[0]

# ================= ENGINE LOOP ================= #

for i,n in enumerate(numbers):

    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"
    window_display=None

    # ===== LOCK MODE =====
    if lock_window is not None:

        state="LOCK"
        window_display=lock_window

        if len(engine)>=lock_window:
            predicted=engine[-lock_window]["group"]
            hit=1 if predicted==g else 0

            if hit==1:
                total_profit += WIN_PROFIT
                miss_streak=0
            else:
                total_profit -= LOSE_LOSS
                miss_streak+=1

            equity_curve.append(total_profit)

        lock_remaining-=1

        if miss_streak>=3 or lock_remaining<=0:
            lock_window=None
            lock_remaining=0
            miss_streak=0

    # ===== SCAN MODE =====
    if lock_window is None and len(engine)>=26:

        best_window=None
        best_ev=-999

        for w in ALLOWED_WINDOWS:
            wr=recent_winrate(engine,w)
            ev=wr*WIN_PROFIT - (1-wr)*LOSE_LOSS
            if ev>best_ev:
                best_ev=ev
                best_window=w

        if best_window:

            predicted=engine[-best_window]["group"]
            hit=1 if predicted==g else 0

            # ===== MODE 1: EV POSITIVE =====
            if best_ev>0:
                state="LOCK_START_EV"
                lock_window=best_window
                lock_remaining=adaptive_lock(engine)
                miss_streak=0
                window_display=lock_window

            # ===== MODE 2: FALLBACK SHORT LOCK =====
            else:
                state="LOCK_START_SHORT"
                lock_window=best_window
                lock_remaining=6
                miss_streak=0
                window_display=lock_window

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_display,
        "state":state
    })

# ================= DASHBOARD ================= #

st.title("🚀 FINAL STABLE DUAL MODE ENGINE")

col1,col2,col3,col4 = st.columns(4)

col1.metric("Total Rounds",len(engine))
col2.metric("Active Window",lock_window)
col3.metric("Lock Remaining",lock_remaining)
col4.metric("Total Profit",round(total_profit,2))

# ===== WINRATE =====
hits=[x["hit"] for x in engine if x["hit"] is not None]
if hits:
    wr=sum(hits)/len(hits)
    st.metric("Winrate %",round(wr*100,2))

    p=wr
    kelly=p - (1-p)/WIN_PROFIT
    kelly=max(0,kelly)*0.5
    st.metric("Kelly % (Half)",round(kelly*100,2))

# ===== VOLATILITY =====
df_hits=pd.DataFrame(engine)
df_hits=df_hits[df_hits["hit"].notna()].tail(20)
if len(df_hits)>5:
    p=df_hits["hit"].mean()
    vol=(p*(1-p))**0.5
    st.metric("Recent Volatility",round(vol,4))

# ===== MAX DRAWDOWN =====
if len(equity_curve)>1:
    peak=np.maximum.accumulate(equity_curve)
    dd=peak - equity_curve
    st.metric("Max Drawdown",round(max(dd),2))

# ===== NEXT GROUP =====
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
        🎯 NEXT GROUP: {next_group}
    </div>
    """,unsafe_allow_html=True)

# ===== HISTORY =====
df_engine=pd.DataFrame(engine)
st.subheader("History")
st.dataframe(df_engine.iloc[::-1],use_container_width=True)

st.caption("FINAL STABLE DUAL MODE | EV + SHORT LOCK | VOL ADAPTIVE | PROFIT TRACK")
