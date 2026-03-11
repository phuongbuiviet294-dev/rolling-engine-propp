import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))   # 8 → 18

MIN_WR = 0.22          # chỉ cần winrate tối thiểu
MIN_TRADES = 12        # đủ mẫu là chạy
GAP = 1                # vào lệnh nhanh

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
cooldown=0

for i,n in enumerate(numbers):
    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    wr=None

    # ===== COOLDOWN =====
    if cooldown>0:
        cooldown-=1
        state="COOLDOWN"

    # ===== EXECUTE =====
    if cooldown==0 and next_signal is not None:
        predicted=next_signal
        hit=1 if predicted==g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS
        state="TRADE"
        last_trade_round=i
        next_signal=None

        if hit==0:
            cooldown=2   # thua nghỉ 2 nhịp

    # ===== GENERATE SIGNAL =====
    if len(engine)>=30 and i-last_trade_round>GAP and cooldown==0:

        best_wr=-1
        best_w=None

        for w in WINDOWS:
            hits=[]
            start=max(w,len(engine)-25)

            for j in range(start,len(engine)):
                if j>=w:
                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )

            if len(hits)>=MIN_TRADES:
                wr_val=np.mean(hits)

                if wr_val>best_wr:
                    best_wr=wr_val
                    best_w=w

        # ===== ENTRY LOGIC (FIX CỨNG) =====
        if best_w is not None and best_wr>=MIN_WR:
            g1=engine[-best_w]["group"]
            if engine[-1]["group"]!=g1:
                next_signal=g1
                window_used=best_w
                wr=best_wr
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":None if wr is None else round(wr*100,2),
        "total_profit":round(total_profit,2),
        "cooldown":cooldown,
        "state":state
    })

# ================= UI =================
st.title("⚡ TURBO TREND PRO — FIXED ENTRY CORE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wrate=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wrate*100,2))

st.caption("Fast Entry | Window 8→18 | Hit-Based Trend | No Repaint")

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET<br>
    🎯 NEXT GROUP: {next_signal}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning...")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
