import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(8,18)   # Adaptive window rộng
LOOKBACK = 26                # tối ưu thực tế
MIN_SAMPLE = 20              # giảm yêu cầu mẫu
GAP = 1                      # vào lệnh liên tục (cực gắt)

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
next_wr=None
next_ev=None

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    wr_val=None
    ev_val=None

    # ===== EXECUTE TRADE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        wr_val=next_wr
        ev_val=next_ev

        hit=1 if predicted==g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== GENERATE SIGNAL (AGGRESSIVE) =====
    if len(engine)>=MIN_SAMPLE and i-last_trade_round>GAP:
        best_w=None
        best_ev=-999
        best_wr=0

        for w in WINDOW_RANGE:
            hits=[]
            start=max(w,len(engine)-LOOKBACK)

            for j in range(start,len(engine)):
                if j>=w:
                    hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)

            if len(hits)>=MIN_SAMPLE:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

                if ev>best_ev:
                    best_ev=ev
                    best_wr=wr
                    best_w=w

        if best_w is not None:
            g1=engine[-best_w]["group"]

            # AGGRESSIVE: bỏ timing filter
            next_signal=g1
            next_window=best_w
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
        "wr":wr_val,
        "ev":ev_val,
        "state":state
    })

# ================= DASHBOARD =================
st.title("⚔ AGGRESSIVE AI — ALL IN PROFIT MODE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Aggressive | Adaptive Window 8–17 | Lookback={LOOKBACK} | Gap={GAP}")

# ================= NEXT =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#b71c1c;color:white;
                border-radius:12px;text-align:center;
                font-size:28px;font-weight:bold'>
        ⚔ ALL-IN READY ⚔
        <br>🎯 NEXT GROUP: {next_signal}
        <br>Window: {next_window}
        <br>WR: {round(next_wr*100,2)}%
        <br>EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Waiting next signal...")

# ================= HISTORY =================
st.subheader("History")
hist=pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist,use_container_width=True)
