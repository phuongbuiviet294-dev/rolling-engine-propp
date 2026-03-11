import streamlit as st
import pandas as pd
import numpy as np
import time

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1.0

WINDOWS = list(range(8,19))   # 8 → 18
LOOKBACK = 26

BASE_GAP = 2
HARD_DD = -40          # lỗ sâu thì nghỉ tạm
COOLDOWN_ROUNDS = 6

# Soft entry
MIN_HIT = 0.30
MIN_EV = -0.05

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
def load_data():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load_data()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
engine = []
total_profit = 0
cooldown = 0
loss_streak = 0
last_trade_round = -999

next_signal = None
next_window = None
next_hit = None
next_ev = None

def calc_hit_profit(window):
    hits = []
    profit = 0
    start = max(window, len(engine) - LOOKBACK)

    for j in range(start, len(engine)):
        if j >= window:
            hit = 1 if engine[j]["group"] == engine[j-window]["group"] else 0
            hits.append(hit)
            profit += WIN_PROFIT if hit else -LOSE_LOSS

    if len(hits) < 12:
        return None

    wr = np.mean(hits)
    ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS
    return wr, ev, profit

for i, n in enumerate(numbers):
    g = get_group(n)
    predicted = None
    hit = None
    pnl = 0
    state = "SCAN"

    # ===== EXECUTE TRADE =====
    if next_signal is not None:
        predicted = next_signal
        hit = 1 if predicted == g else 0
        pnl = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit += pnl
        state = "TRADE"

        last_trade_round = i
        next_signal = None

        if hit:
            loss_streak = 0
        else:
            loss_streak += 1

    # ===== COOLDOWN =====
    if cooldown > 0:
        cooldown -= 1

    # ===== ADAPTIVE GAP =====
    gap = BASE_GAP
    if loss_streak >= 2:
        gap = 4
    if total_profit > 20:
        gap = 1

    # ===== HARD DD → nghỉ tạm =====
    if total_profit <= HARD_DD:
        cooldown = COOLDOWN_ROUNDS

    # ===== FIND BEST WINDOW =====
    best = None
    best_score = -999

    if len(engine) > 40:
        for w in WINDOWS:
            res = calc_hit_profit(w)
            if not res:
                continue
            wr, ev, pf = res

            # 🎯 SCORE = HIT + EV + PROFIT THỰC
            score = wr*0.5 + ev*0.3 + (pf/50)*0.2

            if score > best_score:
                best_score = score
                best = (w, wr, ev, pf)

    # ===== SIGNAL LOGIC (ANTI-SCAN) =====
    if best and cooldown == 0 and i-last_trade_round >= gap:
        w, wr, ev, pf = best

        recent_profit = sum(x["pnl"] for x in engine[-15:] if x["pnl"] is not None)

        allow_trade = (
            wr >= MIN_HIT
            or ev >= MIN_EV
            or recent_profit > 0
        )

        if allow_trade:
            ref_group = engine[-w]["group"] if len(engine)>=w else None
            if ref_group and engine[-1]["group"] != ref_group:
                next_signal = ref_group
                next_window = w
                next_hit = wr
                next_ev = ev
                state = "SIGNAL"

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "pnl": pnl,
        "window": next_window,
        "wr": None if not next_hit else round(next_hit*100,2),
        "ev": None if not next_ev else round(next_ev,3),
        "cooldown": cooldown,
        "state": state,
        "total_profit": round(total_profit,2)
    })

# ================= UI =================
st.title("⚡ TURBO TREND PRO MAX C+++ — ANTI SCAN AI")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits)*100 if hits else 0
c3.metric("Winrate %", round(wr,2))

# ===== STATUS =====
if cooldown>0:
    st.warning(f"🧊 COOLING DOWN — {cooldown} rounds left")

# ===== SIGNAL =====
if next_signal:
    st.markdown(f"""
    <div style='padding:18px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
        🚨 READY TO BET 🚨<br>
        🎯 NEXT GROUP: {next_signal}<br>
        Window: {next_window} | WR: {round(next_hit*100,2)}% | EV: {round(next_ev,3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning market...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
hist = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist, use_container_width=True)
