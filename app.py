import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))  # 8 → 18

BASE_LOOKBACK = 26
BASE_GAP = 2

SOFT_EV = -0.05
HARD_STOPLOSS_STREAK = 5
COOLDOWN_ROUNDS = 6

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
cooldown=0
loss_streak=0
win_streak=0

next_signal=None
next_window=None
next_ev=None
next_wr=None

for i,n in enumerate(numbers):

    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    wr_used=None
    ev_used=None

    # ===== EXECUTE TRADE =====
    if next_signal is not None:
        predicted=next_signal
        window_used=next_window
        wr_used=next_wr
        ev_used=next_ev

        hit = 1 if predicted==g else 0
        profit_change = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit += profit_change

        state="TRADE"
        last_trade_round=i
        next_signal=None

        if hit:
            win_streak+=1
            loss_streak=0
        else:
            loss_streak+=1
            win_streak=0

    # ===== STOPLOSS =====
    if loss_streak >= HARD_STOPLOSS_STREAK:
        cooldown = COOLDOWN_ROUNDS
        loss_streak = 0

    if cooldown>0:
        state="COOLDOWN"
        cooldown-=1

    # ===== REGIME AI =====
    recent_hits=[x["hit"] for x in engine[-20:] if x["hit"] is not None]
    recent_wr=np.mean(recent_hits) if recent_hits else 0

    recent_profit = sum(
        WIN_PROFIT if x["hit"]==1 else -LOSE_LOSS
        for x in engine[-20:] if x["hit"] is not None
    )

    if recent_wr>=0.45 and recent_profit>0:
        regime="TREND"
        dynamic_gap=1
        ev_threshold=SOFT_EV
    elif recent_wr>=0.30:
        regime="SIDEWAY"
        dynamic_gap=3
        ev_threshold=0
    else:
        regime="CHAOS"
        dynamic_gap=5
        ev_threshold=0.05

    # ===== GENERATE SIGNAL =====
    if (
        cooldown==0
        and len(engine)>=40
        and i-last_trade_round>dynamic_gap
    ):
        best_window=None
        best_ev=-999
        best_wr=0

        for w in WINDOWS:
            hits=[]
            start=max(w,len(engine)-BASE_LOOKBACK)
            for j in range(start,len(engine)):
                if j>=w:
                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )
            if len(hits)>=20:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                if ev>best_ev:
                    best_ev=ev
                    best_wr=wr
                    best_window=w

        if best_window is not None and best_ev>ev_threshold:
            g1=engine[-best_window]["group"]
            if engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=best_window
                next_ev=best_ev
                next_wr=best_wr
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
        "state":state,
        "regime":regime,
        "total_profit":round(total_profit,2)
    })

# ================= UI =================
st.title("⚡ TURBO TREND PRO v11 — REGIME AI")

c1,c2,c3,c4=st.columns(4)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))
c4.metric("Market Regime",regime)

st.caption(f"Adaptive Window 8→18 | Regime Gap | Soft Entry EV>{SOFT_EV}")

# ===== SIGNAL =====
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;
                text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window} | WR: {round(next_wr*100,2)}% | EV: {round(next_ev,3)}<br>
    Regime: {regime}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning live market...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
