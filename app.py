import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))   # 8 → 18

st.set_page_config(layout="wide")

# ================= GROUP =================
def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

# ================= LOAD DATA =================
@st.cache_data(ttl=AUTO_REFRESH)
def load_data():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load_data()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine = []
total_profit = 0
last_trade_round = -999

lock_window = None
cooldown = 0
loss_streak = 0

def calc_profit(hit):
    return WIN_PROFIT if hit==1 else -LOSE_LOSS

def window_recent_performance(w):
    hits=[]
    profits=[]
    for i in range(w, len(engine)):
        h = 1 if engine[i]["group"]==engine[i-w]["group"] else 0
        hits.append(h)
        profits.append(calc_profit(h))
    if len(hits)<20:
        return None
    return {
        "wr": np.mean(hits),
        "profit20": sum(profits[-20:]),
        "profit10": sum(profits[-10:]),
        "wr10": np.mean(hits[-10:])
    }

next_signal=None

for i,n in enumerate(numbers):
    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"
    window_used=None

    # ===== EXECUTE TRADE =====
    if next_signal is not None:
        predicted=next_signal
        hit=1 if predicted==g else 0
        pnl=calc_profit(hit)
        total_profit+=pnl
        state="TRADE"
        window_used=lock_window

        if hit==0:
            loss_streak+=1
        else:
            loss_streak=0

        next_signal=None
        last_trade_round=i
    else:
        pnl=0

    # ===== COOLDOWN =====
    if cooldown>0:
        cooldown-=1
        state="COOLDOWN"

    # ===== SELECT / MAINTAIN WINDOW =====
    if cooldown==0 and i-last_trade_round>1:

        change_window=False

        # Check if locked window still good
        if lock_window is not None:
            perf=window_recent_performance(lock_window)
            if perf:
                if perf["profit10"] < -3 or perf["wr10"] < 0.25:
                    change_window=True
            else:
                change_window=True

        # Need new window
        if lock_window is None or change_window:
            best_w=None
            best_score=-999

            for w in WINDOWS:
                perf=window_recent_performance(w)
                if perf:
                    score=perf["profit20"] + perf["wr"]*5
                    if score>best_score:
                        best_score=score
                        best_w=w

            lock_window=best_w

        # ===== GENERATE SIGNAL =====
        if lock_window is not None and len(engine)>=lock_window:
            ref_group=engine[-lock_window]["group"]
            if engine[-1]["group"]!=ref_group:
                next_signal=ref_group
                state="SIGNAL"

    # ===== HARD STOP LOSS =====
    if loss_streak>=4:
        cooldown=5
        loss_streak=0
        state="HARD_STOP"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "pnl":pnl,
        "window":window_used,
        "state":state,
        "total_profit":round(total_profit,2)
    })

# ================= UI =================
st.title("🧠 STICKY WINDOW PRO — Trend Following AI")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(engine))
c2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]
wr=np.mean(hits) if hits else 0
c3.metric("Winrate %",round(wr*100,2))

st.caption(f"Sticky Window Mode | Active Window: {lock_window}")

if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;
                font-size:28px;font-weight:bold'>
        🚨 READY TO BET 🚨<br>
        🎯 NEXT GROUP: {next_signal}<br>
        Window: {lock_window}
    </div>
    """,unsafe_allow_html=True)
else:
    st.info("Scanning market...")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)
