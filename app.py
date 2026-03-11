import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS  = 1

WINDOWS = list(range(8,19))
BASE_LOOKBACK = 26
MIN_DATA = 40

STOPLOSS_STREAK = 3
STOPLOSS_RECENT = -5

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
trade_profits=[]
total_profit=0
last_trade_round=-999
cooldown=0

next_signal=None
next_window=None
next_wr=None
next_ev=None

for i,n in enumerate(numbers):

    g=get_group(n)
    predicted=None; hit=None; state="SCAN"
    window_used=None; wr_show=None; ev_show=None

    # ===== EXECUTE =====
    if next_signal is not None and cooldown==0:
        predicted=next_signal
        window_used=next_window
        wr_show=next_wr
        ev_show=next_ev

        hit = 1 if predicted==g else 0
        profit_change = WIN_PROFIT if hit else -LOSE_LOSS

        total_profit += profit_change
        trade_profits.append(profit_change)

        state="TRADE"
        last_trade_round=i
        next_signal=None

    # ===== PERFORMANCE =====
    recent_profit = sum(trade_profits[-5:]) if len(trade_profits)>=5 else 0

    # ===== LOSS STREAK =====
    loss_streak=0
    for p in reversed(trade_profits):
        if p<0: loss_streak+=1
        else: break

    win_streak=0
    for p in reversed(trade_profits):
        if p>0: win_streak+=1
        else: break

    # ===== STOPLOSS LOGIC =====
    if loss_streak >= STOPLOSS_STREAK:
        cooldown = 5
    elif recent_profit <= STOPLOSS_RECENT:
        cooldown = 5
    elif win_streak >= 2 and recent_profit >= 0:
        cooldown = 0
    elif cooldown>0:
        cooldown -= 1

    # ===== ADAPTIVE GAP =====
    if win_streak>=2:
        GAP=0
    elif recent_profit>=2:
        GAP=1
    elif recent_profit>=-3:
        GAP=2
    else:
        GAP=4

    # ===== ADAPTIVE LOOKBACK =====
    LOOKBACK = BASE_LOOKBACK
    if recent_profit < -5:
        LOOKBACK = 18
    elif recent_profit > 5:
        LOOKBACK = 34

    # ===== SIGNAL SCAN =====
    if len(engine)>=MIN_DATA and i-last_trade_round>GAP and cooldown==0:

        best_window=None
        best_profit=-999
        best_wr=0
        best_ev=0

        for w in WINDOWS:
            hits=[]
            sim_profit=0
            start=max(w,len(engine)-LOOKBACK)

            for j in range(start,len(engine)):
                if j>=w:
                    h = 1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    hits.append(h)
                    sim_profit += WIN_PROFIT if h else -LOSE_LOSS

            if len(hits)>=15:
                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
                if sim_profit>best_profit:
                    best_profit=sim_profit
                    best_window=w
                    best_wr=wr
                    best_ev=ev

        allow=False
        if best_window is not None:
            if win_streak>=2:
                allow=True
            elif recent_profit>=-2 and best_ev>0:
                allow=True
            elif best_wr>0.40 and best_ev>0:
                allow=True
            elif best_ev>0.25:
                allow=True

        if allow:
            g1=engine[-best_window]["group"]
            if engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=best_window
                next_wr=best_wr
                next_ev=best_ev
                state="SIGNAL"

    if cooldown>0:
        state="COOLDOWN"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":None if wr_show is None else round(wr_show*100,2),
        "ev":None if ev_show is None else round(ev_show,3),
        "recent_profit":round(recent_profit,2),
        "loss_streak":loss_streak,
        "cooldown":cooldown,
        "state":state,
        "total_profit":round(total_profit,2)
    })

# ================= UI =================
st.title("🛑⚡ TURBO TREND PRO v8 — AUTO STOPLOSS")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Auto Stoploss | Window=8→18 | Lookback={LOOKBACK} | Gap={GAP}")

# ===== SIGNAL =====
if next_signal is not None and cooldown==0:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {round(next_wr*100,2)}%<br>
    EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
elif cooldown>0:
    st.warning(f"🧊 COOLING DOWN — {cooldown} rounds left")
else:
    st.info("Scanning trend...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
