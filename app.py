import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = list(range(8,19))   # full chu kỳ

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
next_signal=None
next_window=None

win_streak=0
loss_streak=0

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        hit=1 if predicted==g else 0

        if hit:
            total_profit+=WIN_PROFIT
            win_streak+=1
            loss_streak=0
        else:
            total_profit-=LOSE_LOSS
            loss_streak+=1
            win_streak=0

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== EQUITY =====
    profits=[x["profit"] for x in engine[-20:] if "profit" in x]
    if len(profits)>=10 and profits[-1]<profits[0]:
        equity_bad=True
    else:
        equity_bad=False

    # ===== ADAPTIVE LOOKBACK =====
    if equity_bad:
        LOOKBACK=40
    elif win_streak>=3:
        LOOKBACK=120
    else:
        LOOKBACK=70

    # ===== ADAPTIVE GAP =====
    if loss_streak>=2:
        GAP=5
    elif win_streak>=2:
        GAP=2
    else:
        GAP=3

    # ===== SCAN WINDOWS BY REAL PROFIT =====
    if len(engine)>LOOKBACK and i-last_trade_round>GAP:
        best_window=None
        best_profit=-999
        best_trades=0

        for w in WINDOWS:
            profit=0; hits=0; trades=0
            start=max(w,len(engine)-LOOKBACK)

            for j in range(start,len(engine)):
                if j>=w:
                    trades+=1
                    if engine[j]["group"]==engine[j-w]["group"]:
                        profit+=WIN_PROFIT; hits+=1
                    else:
                        profit-=LOSE_LOSS

            if trades>=10:
                stability=profit/trades
                if profit>0 and hits>=6 and stability>0.12:
                    if profit>best_profit or (profit==best_profit and trades>best_trades):
                        best_profit=profit
                        best_trades=trades
                        best_window=w

        # ===== TURBO ENTRY =====
        if best_window is not None:
            g1=engine[-best_window]["group"]
            if engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=best_window
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "state":state,
        "profit":round(total_profit,2)
    })

# ================= UI =================
st.title("⚡ TURBO PRO+ MAX — LIVE REAL PROFIT")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Adaptive Lookback={LOOKBACK} | Adaptive Gap={GAP} | Windows=8→18")

# ===== SIGNAL =====
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;
                font-size:26px;font-weight:bold'>
    🚀 TURBO SIGNAL 🚀<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning live market...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
