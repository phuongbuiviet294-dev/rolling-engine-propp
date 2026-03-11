import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9, 15]
FIXED_LOOKBACK = 26
AUTO_LOOKBACK_RANGE = range(20, 41)
GAP_RANGE = range(3, 7)

PERIOD = 120   # số round để đánh giá lại mode

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

# ================= CORE ENGINE =================
def simulate_engine(LOOKBACK, GAP):
    total_profit = 0
    engine = []
    last_trade_round = -999
    next_signal = None

    for i, n in enumerate(numbers):
        g = get_group(n)
        predicted=None; hit=None; state="SCAN"
        window_used=None; wr_val=None; ev_val=None

        # ===== EXECUTE =====
        if next_signal is not None:
            predicted = next_signal
            hit = 1 if predicted == g else 0
            total_profit += WIN_PROFIT if hit else -LOSE_LOSS
            state = "TRADE"
            last_trade_round = i
            next_signal = None

        # ===== GENERATE =====
        if len(engine) >= 40 and i - last_trade_round > GAP:
            best_window=None; best_ev=-999; best_wr=0

            for w in WINDOWS:
                recent_hits=[]
                start=max(w, len(engine)-LOOKBACK)

                for j in range(start, len(engine)):
                    if j>=w:
                        recent_hits.append(
                            1 if engine[j]["group"] == engine[j-w]["group"] else 0
                        )

                if len(recent_hits)>=20:
                    wr=np.mean(recent_hits)
                    ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                    if ev>best_ev:
                        best_ev=ev; best_window=w; best_wr=wr

            if best_window is not None and best_wr>0.29 and best_ev>0:
                g1 = engine[-best_window]["group"]
                if engine[-1]["group"] != g1:
                    next_signal = g1
                    state="SIGNAL"
                    window_used=best_window
                    wr_val=best_wr
                    ev_val=best_ev

        engine.append({
            "round": i+1,
            "number": n,
            "group": g,
            "predicted": predicted,
            "hit": hit,
            "state": state,
            "window": window_used,
            "wr": wr_val,
            "ev": ev_val,
            "profit": total_profit
        })

    return total_profit, engine

# ================= AUTO OPTIMIZER =================
def auto_optimize():
    best_profit=-999
    best_cfg=(None,None)

    for lb in AUTO_LOOKBACK_RANGE:
        for gap in GAP_RANGE:
            p,_ = simulate_engine(lb,gap)
            if p>best_profit:
                best_profit=p
                best_cfg=(lb,gap)
    return best_profit, best_cfg

# ================= MODE DECISION =================
fixed_profit, fixed_engine = simulate_engine(FIXED_LOOKBACK, 4)
auto_profit, (auto_lb, auto_gap) = auto_optimize()
auto_profit, auto_engine = simulate_engine(auto_lb, auto_gap)

if auto_profit > fixed_profit * 1.05:
    MODE = "AUTO PERIODIC"
    engine = auto_engine
    total_profit = auto_profit
    cfg = f"Auto Lookback={auto_lb} Gap={auto_gap}"
else:
    MODE = "FIXED STABLE"
    engine = fixed_engine
    total_profit = fixed_profit
    cfg = f"Fixed Lookback={FIXED_LOOKBACK} Gap=4"

# ================= LIVE METRICS =================
hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0

last = engine[-1]
next_group = None
for x in reversed(engine):
    if x["state"]=="SIGNAL":
        next_group = x["predicted"]
        break

# ================= UI =================
st.title("🧠 AUTO PERIODIC PRO+ — HYBRID LIVE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Live Profit", round(total_profit,2))
c3.metric("Winrate %", round(wr*100,2))

st.caption(f"Mode: {MODE} | {cfg}")

if next_group is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_group}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1], use_container_width=True)
