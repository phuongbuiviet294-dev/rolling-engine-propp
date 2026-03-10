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
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# =========================================================
# 🔧 PHASE 1 — AUTO OPTIMIZE ON PAST DATA (1 LẦN DUY NHẤT)
# =========================================================
@st.cache_data(show_spinner=False)
def auto_optimize(numbers):

    def backtest(LOOKBACK, GAP):
        engine=[]
        total_profit=0
        last_trade_round=-999
        next_signal=None

        for i,n in enumerate(numbers):
            g=get_group(n)

            # EXECUTE
            if next_signal is not None:
                hit = 1 if next_signal==g else 0
                total_profit += WIN_PROFIT if hit else -LOSE_LOSS
                last_trade_round=i
                next_signal=None

            # GENERATE
            if len(engine)>=40 and i-last_trade_round>GAP:
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

            engine.append({"group":g})

        return total_profit

    best_profit=-999
    best_cfg=None

    for LOOKBACK in range(20,41):
        for GAP in range(2,7):
            p=backtest(LOOKBACK,GAP)
            if p>best_profit:
                best_profit=p
                best_cfg=(LOOKBACK,GAP)

    return best_cfg, best_profit

(best_LOOKBACK, best_GAP), best_profit = auto_optimize(numbers)

# =========================================================
# 🔒 PHASE 2 — LIVE ENGINE (KHÓA CẤU HÌNH)
# =========================================================
engine=[]
total_profit=0
last_trade_round=-999
next_signal=None
next_window=None
next_wr=None
next_ev=None

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None; wr_used=None; ev_used=None

    # EXECUTE
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        wr_used=next_wr
        ev_used=next_ev
        hit=1 if predicted==g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS
        state="TRADE"
        last_trade_round=i
        next_signal=None

    # GENERATE (LIVE ONLY)
    if len(engine)>=40 and i-last_trade_round>best_GAP:
        best_window=None; best_ev=-999; best_wr=0

        for w in WINDOWS:
            hits=[]
            start=max(w,len(engine)-best_LOOKBACK)
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
        "wr":None if wr_used is None else round(wr_used*100,2),
        "ev":None if ev_used is None else round(ev_used,3),
        "state":state
    })

# ================= UI =================
st.title("🧠 HYBRID LIVE MODE — AUTO + FIXED")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Live Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"🔒 Locked Config → Window Auto | Lookback={best_LOOKBACK} | Gap={best_GAP}")

# NEXT SIGNAL
if next_signal:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 LIVE NEXT GROUP 🚨<br>
    🎯 GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {round(next_wr*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

# HISTORY
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
