import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))   # 8 → 18

# ===== AGGRESSIVE FILTER =====
MIN_HIT_RATE = 0.22
MIN_EV = -0.15
SOFT_PROFIT_ALLOW = -40

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
engine = []
total_profit = 0
loss_streak = 0
cooldown = 0
last_trade_round = -999

def calc_recent_profit(hist, n=25):
    p = 0
    for h in hist[-n:]:
        if h["hit"] == 1:
            p += WIN_PROFIT
        elif h["hit"] == 0:
            p -= LOSE_LOSS
    return p

for i,n in enumerate(numbers):
    g = get_group(n)

    predicted=None
    hit=None
    state="SCAN"
    window_used=None
    wr=None
    ev=None
    profit_change=0

    # ===== COOLDOWN =====
    if cooldown>0:
        cooldown-=1
        state="COOLDOWN"

    # ===== EXECUTE =====
    if cooldown==0 and "next_signal" in locals() and next_signal is not None:
        predicted = next_signal
        window_used = next_window
        wr = next_wr
        ev = next_ev

        hit = 1 if predicted==g else 0
        profit_change = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit += profit_change

        state="TRADE"
        last_trade_round=i
        next_signal=None

        if hit==0:
            loss_streak+=1
        else:
            loss_streak=0

        if loss_streak>=4:
            cooldown=4
            loss_streak=0

    # ===== GENERATE SIGNAL =====
    if len(engine)>=40 and i-last_trade_round>1 and cooldown==0:

        best_score=-999
        best=None

        for w in WINDOWS:
            hits=[]
            start=max(w,len(engine)-26)

            for j in range(start,len(engine)):
                if j>=w:
                    hits.append(
                        1 if engine[j]["group"]==engine[j-w]["group"] else 0
                    )

            if len(hits)>=20:
                wr_val=np.mean(hits)
                ev_val=wr_val*WIN_PROFIT-(1-wr_val)*LOSE_LOSS
                pf_recent=calc_recent_profit(engine,25)
                hr_recent=np.mean([h["hit"] for h in engine[-25:] if h["hit"] is not None] or [0])

                score = (
                    wr_val*100
                    + ev_val*10
                    + pf_recent*0.3
                    + hr_recent*50
                )

                # ===== AGGRESSIVE ENTRY =====
                if (
                    hr_recent >= MIN_HIT_RATE and
                    (
                        ev_val >= MIN_EV
                        or pf_recent > 0
                        or hr_recent > 0.40
                    )
                ):
                    if score>best_score:
                        best_score=score
                        best=(w,wr_val,ev_val)

        if best is not None:
            w,wr_val,ev_val = best
            g1 = engine[-w]["group"]

            if engine[-1]["group"]!=g1:
                next_signal=g1
                next_window=w
                next_wr=wr_val
                next_ev=ev_val
                state="SIGNAL"

    engine.append({
        "round":i+1,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_used,
        "wr":None if wr is None else round(wr*100,2),
        "ev":None if ev is None else round(ev,3),
        "profit_change":profit_change,
        "total_profit":round(total_profit,2),
        "loss_streak":loss_streak,
        "cooldown":cooldown,
        "state":state
    })

# ================= UI =================
st.title("⚡ TURBO TREND PRO v12.2 — AGGRESSIVE")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wrate=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wrate*100,2))

st.caption("Aggressive Trend Mode | Window 8→18 | Hit+EV+Profit Score")

# ===== SIGNAL =====
if "next_signal" in locals() and next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 ENTER TRADE<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window} | WR: {round(next_wr*100,2)}% | EV: {round(next_ev,3)}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning trend...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
