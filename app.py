import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]

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
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

df = load()
if df.empty or "number" not in df.columns:
    st.error("Data lỗi hoặc thiếu cột 'number'")
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()
groups = [get_group(n) for n in numbers]

# =========================================================
# 1️⃣ FIND MAX PROFIT PERIOD (LOCK ZONE)
# =========================================================
def backtest_period(start, end, lookback, gap, window):
    profit = 0
    last_trade = -999
    next_signal = None
    
    for i in range(start, end):
        g = groups[i]

        if next_signal is not None:
            hit = 1 if g == next_signal else 0
            profit += WIN_PROFIT if hit else -LOSE_LOSS
            last_trade = i
            next_signal = None

        if i - last_trade > gap and i > start + lookback + window:
            hits = []
            for j in range(i-lookback, i):
                if j-window >= start:
                    hits.append(1 if groups[j]==groups[j-window] else 0)

            if len(hits) >= 15:
                wr = np.mean(hits)
                ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS
                if wr > 0.29 and ev > 0:
                    pred = groups[i-window]
                    if pred != groups[i-1]:
                        next_signal = pred
    return profit


best_profit = -999
best_zone = None
best_params = None

N = len(groups)
ZONE = 600  # mỗi block ~2 ngày

for start in range(0, N-ZONE, ZONE//2):
    end = start + ZONE
    
    for w in WINDOWS:
        for lb in range(22, 36):
            for gp in range(2, 6):
                pf = backtest_period(start, end, lb, gp, w)
                if pf > best_profit:
                    best_profit = pf
                    best_zone = (start, end)
                    best_params = (w, lb, gp)

LOCK_START, LOCK_END = best_zone
LOCK_WINDOW, LOCK_LOOKBACK, LOCK_GAP = best_params

# =========================================================
# 2️⃣ LIVE ENGINE (LOCKED PARAMS — NO REOPTIMIZE)
# =========================================================
def run_live():
    engine=[]
    total_profit=0
    last_trade=-999
    next_signal=None
    
    for i in range(LOCK_END, N):
        g=groups[i]
        predicted=None
        hit=None
        state="SCAN"

        # EXECUTE
        if next_signal is not None:
            predicted=next_signal
            hit=1 if g==predicted else 0
            total_profit += WIN_PROFIT if hit else -LOSE_LOSS
            state="TRADE"
            last_trade=i
            next_signal=None

        # GENERATE
        if i-last_trade>LOCK_GAP and i>LOCK_LOOKBACK+LOCK_WINDOW:
            hits=[]
            for j in range(i-LOCK_LOOKBACK, i):
                if j-LOCK_WINDOW>=0:
                    hits.append(1 if groups[j]==groups[j-LOCK_WINDOW] else 0)

            if len(hits)>=15:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                if wr>0.29 and ev>0:
                    pred=groups[i-LOCK_WINDOW]
                    if pred!=groups[i-1]:
                        next_signal=pred
                        state="SIGNAL"

        engine.append({
            "round":i+1,
            "group":g,
            "predicted":predicted,
            "hit":hit,
            "state":state,
            "profit":round(total_profit,2)
        })
    return engine,next_signal,total_profit

engine,next_signal,live_profit=run_live()

# =========================================================
# DASHBOARD
# =========================================================
st.title("🔒 AUTO MAX PROFIT LOCK PRO ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("LOCK PROFIT",round(best_profit,2))
c2.metric("LIVE PROFIT",round(live_profit,2))
c3.metric("TOTAL ROUNDS",len(engine))

st.caption(f"""
LOCK ZONE: Rounds {LOCK_START} → {LOCK_END}
WINDOW={LOCK_WINDOW} | LOOKBACK={LOCK_LOOKBACK} | GAP={LOCK_GAP}
""")

# NEXT SIGNAL
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;
                text-align:center;font-size:28px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning...")

# HISTORY
st.subheader("Live History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
