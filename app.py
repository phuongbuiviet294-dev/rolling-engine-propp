import streamlit as st
import pandas as pd
import numpy as npimport streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOW = [9,15]
LOOKBACK = 26
GAP = 3

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
numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine=[]
total_profit=0
last_trade_round=-999
next_signal=None
next_wr=None
next_ev=None

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        hit=1 if predicted==g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS
        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== GENERATE (LIVE ONLY) =====
    if i == len(numbers)-1:  # chỉ tính tại thời điểm mới nhất
        if len(engine)>=40 and i-last_trade_round>GAP:
            recent_hits=[]
            start=max(WINDOW,len(engine)-LOOKBACK)

            for j in range(start,len(engine)):
                if j>=WINDOW:
                    recent_hits.append(
                        1 if engine[j]["group"]==engine[j-WINDOW]["group"] else 0
                    )

            if len(recent_hits)>=20:
                wr=np.mean(recent_hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

                if wr>0.29 and ev>0:
                    g1=engine[-WINDOW]["group"]
                    if engine[-1]["group"]!=g1:
                        next_signal=g1
                        next_wr=wr
                        next_ev=ev
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
st.title("🔒 LIVE FIXED ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))
hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption("History Locked • No Re-Optimization • True Live Signal")

if next_signal is not None:
    st.success(f"🎯 NEXT GROUP: {next_signal} | WR={round(next_wr*100,2)}% | EV={round(next_ev,3)}")
else:
    st.info("No valid signal")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9,15]
CYCLE_LEN = 300

WR_THRESHOLD = 0.27
EV_THRESHOLD = -0.05

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

# ================= WINDOW OPT =================
def find_best_window(engine_slice, lookback):
    best_window=None; best_ev=-999; best_wr=0
    for w in WINDOWS:
        hits=[]
        start=max(w,len(engine_slice)-lookback)
        for j in range(start,len(engine_slice)):
            if j>=w:
                hits.append(1 if engine_slice[j]["group"]==engine_slice[j-w]["group"] else 0)
        if len(hits)>=15:
            wr=np.mean(hits)
            ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
            if ev>best_ev:
                best_ev=ev; best_window=w; best_wr=wr
    return best_window,best_wr,best_ev

# ================= ENGINE =================
engine=[]
total_profit=0
last_trade_round=-999

next_signal=None
next_window=None
next_wr=None
next_ev=None

locked_window=None
cycle_id=0

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None; rolling_wr=None; ev_value=None

    # ===== SHORT-TERM FORM =====
    recent_hits=[x["hit"] for x in engine[-15:] if x["hit"] is not None]
    short_wr=np.mean(recent_hits) if len(recent_hits)>=5 else 0.5

    # ===== AUTO LOOKBACK =====
    if short_wr>=0.60:
        LOOKBACK=20
    elif short_wr>=0.45:
        LOOKBACK=26
    else:
        LOOKBACK=34

    # ===== AUTO GAP =====
    if short_wr>=0.60:
        GAP=1
    elif short_wr>=0.45:
        GAP=2
    else:
        GAP=4

    # ===== LOCK WINDOW EACH CYCLE =====
    if i % CYCLE_LEN == 0 and i>0:
        cycle_id+=1
        hist_slice=engine[max(0,i-CYCLE_LEN):i]
        w,wr,ev=find_best_window(hist_slice,LOOKBACK)
        locked_window=w

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        rolling_wr=next_wr
        ev_value=next_ev

        hit=1 if predicted==g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== GENERATE =====
    if locked_window is not None and len(engine)>=30 and i-last_trade_round>GAP:
        hits=[]
        start=max(locked_window,len(engine)-LOOKBACK)
        for j in range(start,len(engine)):
            if j>=locked_window:
                hits.append(1 if engine[j]["group"]==engine[j-locked_window]["group"] else 0)

        if len(hits)>=15:
            wr=np.mean(hits)
            ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

            if wr>WR_THRESHOLD and ev>EV_THRESHOLD:
                g1=engine[-locked_window]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    next_window=locked_window
                    next_wr=wr
                    next_ev=ev
                    state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":None if rolling_wr is None else round(rolling_wr*100,2),
        "ev":None if ev_value is None else round(ev_value,3),
        "short_wr":round(short_wr*100,1),
        "lookback":LOOKBACK,
        "gap":GAP,
        "cycle":cycle_id,
        "locked_window":locked_window,
        "state":state
    })

# ================= UI =================
st.title("⚡ TURBO LIVE — AUTO PARAM")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))
hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption("Auto Lookback + Auto Gap + Cycle Lock")

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;
                font-size:26px;font-weight:bold'>
    ⚡ READY TO BET ⚡<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {round(next_wr*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning...")

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
