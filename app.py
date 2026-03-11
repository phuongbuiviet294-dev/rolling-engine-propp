import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))   # 8 → 18 theo thị trường
LOOKBACK = 26
BASE_GAP = 2
MIN_TRADE_TO_START = 5

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
total_profit=0
last_trade_round=-999
trade_profits=[]

next_signal=None
next_window=None
next_wr=None
next_ev=None

for i,n in enumerate(numbers):
    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    wr=None
    ev=None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        wr=next_wr
        ev=next_ev

        hit=1 if predicted==g else 0
        profit = WIN_PROFIT if hit else -LOSE_LOSS

        total_profit += profit
        trade_profits.append(profit)

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== RECENT PROFIT =====
    recent_profit=sum(trade_profits[-5:]) if len(trade_profits)>=5 else 0

    # ===== ADAPTIVE GAP =====
    if recent_profit > 2:
        GAP = 1
    elif recent_profit >= -1:
        GAP = BASE_GAP
    else:
        GAP = BASE_GAP + 2

    # ===== GENERATE SIGNAL =====
    if len(engine)>=40 and i-last_trade_round>GAP:

        best_window=None
        best_window_profit=-999
        best_wr=0
        best_ev=0

        for w in WINDOWS:
            hits=[]
            profits=[]
            start=max(w,len(engine)-LOOKBACK)

            for j in range(start,len(engine)):
                if j>=w:
                    h = 1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    hits.append(h)
                    profits.append(WIN_PROFIT if h else -LOSE_LOSS)

            if len(hits)>=20:
                window_profit=sum(profits)
                wr_=np.mean(hits)
                ev_=wr_*WIN_PROFIT-(1-wr_)*LOSE_LOSS

                # ⭐ CHỌN WINDOW THEO PROFIT THẬT
                if window_profit > best_window_profit:
                    best_window_profit=window_profit
                    best_window=w
                    best_wr=wr_
                    best_ev=ev_

        if best_window is not None:
            g1=engine[-best_window]["group"]

            allow_trade=False

            # 🚀 SMART START
            if len(trade_profits)<MIN_TRADE_TO_START:
                if best_ev>0:
                    allow_trade=True
            else:
                # 📈 TREND FILTER
                if best_ev>0 and recent_profit>=-1:
                    allow_trade=True

            if allow_trade and engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=best_window
                next_wr=best_wr
                next_ev=best_ev
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":None if wr is None else round(wr*100,2),
        "ev":None if ev is None else round(ev,3),
        "recent_profit":recent_profit,
        "state":state,
        "total_profit":round(total_profit,2)
    })

# ================= UI =================
st.title("🚀 TURBO TREND PRO v3 — REAL MARKET")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption("Trend Mode | Window by REAL PROFIT | Adaptive Gap")

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;
                text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {round(next_wr*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning trend...")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
