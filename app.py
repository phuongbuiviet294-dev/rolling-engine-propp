import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = list(range(8,19))   # full chu kỳ thị trường

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

RECENT_SPAN = 120   # vùng thị trường hiện tại

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        hit=1 if predicted==g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS
        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== SCAN WINDOW REAL PROFIT =====
    if len(engine)>150 and i-last_trade_round>2:
        best_window=None
        best_score=-999

        for w in WINDOWS:
            profit_all=0; trades_all=0
            profit_recent=0; trades_recent=0

            for j in range(w,len(engine)):
                pnl = WIN_PROFIT if engine[j]["group"]==engine[j-w]["group"] else -LOSE_LOSS
                profit_all += pnl
                trades_all += 1

                if j > len(engine)-RECENT_SPAN:
                    profit_recent += pnl
                    trades_recent += 1

            if trades_all>=20 and trades_recent>=5:
                score = profit_all*0.6 + profit_recent*1.4
                if score>0 and score>best_score:
                    best_score=score
                    best_window=w

        # ===== ENTRY =====
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
st.title("⚡ TURBO PRO+ MAX REAL — LIVE PROFIT")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption("Window chọn theo PROFIT THẬT • Ưu tiên thị trường hiện tại")

# ===== SIGNAL =====
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;
                font-size:26px;font-weight:bold'>
    🚀 REAL SIGNAL 🚀<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning live market...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
