import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = list(range(8,19))  # ✅ FULL ADAPTIVE WINDOW

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

# ================= MARKET ADAPTIVE =================
def market_adaptive(engine):
    recent = [x for x in engine[-25:] if x["hit"] is not None]
    if len(recent) < 10:
        return 26, 4
    
    wr = np.mean([x["hit"] for x in recent])
    
    if wr >= 0.38:
        return 22, 2   # thị trường đẹp → vào nhanh
    elif wr >= 0.32:
        return 26, 3
    else:
        return 30, 5   # thị trường xấu → giãn lệnh

# ================= WINDOW REAL PROFIT =================
def window_real_profit(engine, w, lookback):
    hits=[]
    start=max(w,len(engine)-lookback)
    
    for j in range(start,len(engine)):
        if j>=w:
            hit = 1 if engine[j]["group"]==engine[j-w]["group"] else 0
            hits.append(hit)
    
    if len(hits)<20:
        return -999,0,0
    
    profit=sum([WIN_PROFIT if h else -LOSE_LOSS for h in hits])
    wr=np.mean(hits)
    count=sum(hits)
    return profit,wr,count

# ================= ENGINE =================
engine=[]
total_profit=0
last_trade_round=-999

next_signal=None
next_window=None
next_wr=None
next_profit=None

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None; wr_used=None; profit_used=None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        wr_used=next_wr
        profit_used=next_profit

        hit=1 if predicted==g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== ADAPTIVE PARAM =====
    LOOKBACK,GAP=market_adaptive(engine)

    # ===== GENERATE =====
    if len(engine)>=40 and i-last_trade_round>GAP:
        best_window=None
        best_profit=-999
        best_wr=0
        best_hits=0

        for w in WINDOWS:
            profit,wr,hits=window_real_profit(engine,w,LOOKBACK)

            if profit>best_profit:
                best_profit=profit
                best_window=w
                best_wr=wr
                best_hits=hits

        # ===== REAL MONEY FILTER =====
        if (
            best_window is not None
            and best_profit>0
            and best_wr>0.30
            and best_hits>=6
        ):
            g1=engine[-best_window]["group"]
            if engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=best_window
                next_wr=best_wr
                next_profit=best_profit
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":None if wr_used is None else round(wr_used*100,2),
        "window_profit":profit_used,
        "state":state,
        "total_profit":round(total_profit,2)
    })

# ================= UI =================
st.title("⚡ TURBO ADAPTIVE PRO+ MAX — FULL WINDOW")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption("Adaptive Lookback + Adaptive Gap + Window 8→18 chọn theo PROFIT THẬT")

# ================= NEXT SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    🪟 Best Window: {next_window}<br>
    📈 WR: {round(next_wr*100,2)}%<br>
    💰 Window Profit: {round(next_profit,2)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
