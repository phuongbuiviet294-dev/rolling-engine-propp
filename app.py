import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(8,19)
LOOKBACK = 26
BASE_GAP = 2

# ===== V12 FILTER =====
RECENT_N = 20
MIN_RECENT_TRADES = 8
MIN_HIT_RATE = 0.38      # ≥38% hit gần đây
MIN_EV = 0.05            # EV tối thiểu
SOFT_PROFIT_ALLOW = -5   # âm nhẹ vẫn cho vào

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

loss_streak=0
cooldown=0

def calc_gap():
    if loss_streak>=3: return 4
    if loss_streak==2: return 3
    return BASE_GAP

def calc_recent_trend(w):
    hits=[]
    profit=0
    trades=0
    for row in engine[-RECENT_N:]:
        if row["window"]==w and row["hit"] is not None:
            trades+=1
            hits.append(row["hit"])
            profit += WIN_PROFIT if row["hit"]==1 else -LOSE_LOSS
    if trades < MIN_RECENT_TRADES:
        return None
    hit_rate = sum(hits)/len(hits)
    return hit_rate, profit

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"
    used_window=None

    # ===== COOLDOWN =====
    if cooldown>0:
        cooldown-=1
        state="COOLDOWN"

    # ===== EXECUTE =====
    elif next_signal is not None:
        predicted=next_signal
        used_window=next_window

        hit=1 if predicted==g else 0
        change = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit+=change

        if hit: loss_streak=0
        else: loss_streak+=1

        state="TRADE"
        last_trade_round=i
        next_signal=None

        if loss_streak>=4:
            cooldown=5

    # ===== GENERATE =====
    else:
        gap=calc_gap()
        if len(engine)>LOOKBACK and i-last_trade_round>gap:

            best_score=-999
            best_w=None
            best_ev=0
            best_hr=0
            best_pf=0

            for w in WINDOW_RANGE:
                # ===== Pattern stats =====
                hits=[]
                start=max(w,len(engine)-LOOKBACK)
                for j in range(start,len(engine)):
                    if j>=w:
                        hits.append(1 if engine[j]["group"]==engine[j-w]["group"] else 0)
                if len(hits)<20:
                    continue

                wr=np.mean(hits)
                ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

                # ===== Trend thật =====
                trend=calc_recent_trend(w)
                if trend is None:
                    continue
                hr_recent, pf_recent = trend

                # ===== V12 FILTER =====
                if hr_recent < MIN_HIT_RATE:
                    continue
                if pf_recent < SOFT_PROFIT_ALLOW:
                    continue
                if ev < MIN_EV:
                    continue

                # ===== Score =====
                score = hr_recent*0.6 + ev*0.3 + (pf_recent/10)*0.1

                if score>best_score:
                    best_score=score
                    best_w=w
                    best_ev=ev
                    best_hr=hr_recent
                    best_pf=pf_recent

            if best_w is not None:
                g1=engine[-best_w]["group"]
                if engine[-1]["group"]!=g1:
                    next_signal=g1
                    next_window=best_w
                    state="SIGNAL"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":used_window,
        "state":state,
        "loss_streak":loss_streak,
        "cooldown":cooldown,
        "total_profit":round(total_profit,1)
    })

# ================= UI =================
st.title("🧠 TURBO HIT-TREND PRO MAX — V12")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,1))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption("V12 | Hit-Trend + EV Filter | Window 8→18 | Adaptive Gap")

if cooldown>0:
    st.warning(f"🧊 COOLING DOWN — {cooldown} rounds left")

if next_signal is not None and cooldown==0:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;
                font-size:28px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning trend…")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
