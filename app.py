import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [9, 15]

REOPT_EVERY = 200      # ✅ tối ưu lại mỗi X round
LIVE_LOOKBACK = 300    # chỉ dùng dữ liệu gần
MIN_SAMPLES = 40

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

# ================= OPTIMIZER =================
def optimize_params(engine_slice):
    best_profit = -999
    best_cfg = (26, 4)

    for LOOKBACK in range(20, 41):
        for GAP in range(3, 7):
            profit = 0
            last_trade = -999
            next_sig = None

            for i in range(len(engine_slice)):
                g = engine_slice[i]["group"]

                if next_sig is not None:
                    hit = 1 if next_sig == g else 0
                    profit += WIN_PROFIT if hit else -LOSE_LOSS
                    last_trade = i
                    next_sig = None

                if i < MIN_SAMPLES or i - last_trade <= GAP:
                    continue

                best_w = None
                best_ev = -999
                best_wr = 0

                for w in WINDOWS:
                    hits = []
                    start = max(w, i - LOOKBACK)
                    for j in range(start, i):
                        if j >= w:
                            hits.append(
                                1 if engine_slice[j]["group"] == engine_slice[j-w]["group"] else 0
                            )
                    if len(hits) >= 20:
                        wr = np.mean(hits)
                        ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS
                        if ev > best_ev:
                            best_ev = ev
                            best_w = w
                            best_wr = wr

                if best_w and best_wr > 0.29 and best_ev > 0:
                    g1 = engine_slice[i-best_w]["group"]
                    if engine_slice[i-1]["group"] != g1:
                        next_sig = g1

            if profit > best_profit:
                best_profit = profit
                best_cfg = (LOOKBACK, GAP)

    return best_cfg

# ================= LIVE ENGINE =================
engine = []
total_profit = 0
last_trade_round = -999

next_signal = None
next_window = None
next_wr = None
next_ev = None

LOOKBACK = 26
GAP = 4

for i, n in enumerate(numbers):
    g = get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None; rolling_wr=None; ev_value=None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted = next_signal
        window_used = next_window
        rolling_wr = next_wr
        ev_value = next_ev

        hit = 1 if predicted == g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== PERIODIC OPTIMIZE =====
    if i > 0 and i % REOPT_EVERY == 0 and len(engine) > LIVE_LOOKBACK:
        slice_engine = engine[-LIVE_LOOKBACK:]
        LOOKBACK, GAP = optimize_params(slice_engine)

    # ===== GENERATE SIGNAL =====
    if len(engine) >= MIN_SAMPLES and i - last_trade_round > GAP:
        best_window=None; best_ev=-999; best_wr=0

        for w in WINDOWS:
            hits=[]
            start=max(w,len(engine)-LOOKBACK)
            for j in range(start,len(engine)):
                if j>=w:
                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )
            if len(hits)>=20:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                if ev>best_ev:
                    best_ev=ev; best_window=w; best_wr=wr

        if best_window and best_wr>0.29 and best_ev>0:
            g1=engine[-best_window]["group"]
            if engine[-1]["group"]!=g1:
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
        "wr":None if rolling_wr is None else round(rolling_wr*100,2),
        "ev":None if ev_value is None else round(ev_value,3),
        "state":state
    })

# ================= UI =================
st.title("🚀 AUTO PERIODIC PRO — LIVE ENGINE")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Live Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Periodic Optimize: every {REOPT_EVERY} rounds | Windows={WINDOWS} | Lookback={LOOKBACK} | Gap={GAP}")

# ===== NEXT SIGNAL =====
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {round(next_wr*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

# ===== HISTORY =====
st.subheader("Live History (Locked — No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
