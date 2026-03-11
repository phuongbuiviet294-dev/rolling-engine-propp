# ================= TURBO TREND PRO v12.1 =================
# Real Trade Mode — No Repaint — Turbo Start

import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))   # 8 → 18
LOOKBACK = 26

# ===== TURBO MODE =====
TURBO_MODE = True
WARMUP_TRADES = 8        # cho trade sớm lấy dữ liệu
BASE_GAP = 1             # vào lệnh nhanh
COOLDOWN_AFTER_LOSS = 2

MIN_HIT_RATE = 0.30
MIN_EV = -0.05
SOFT_PROFIT_ALLOW = -15

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
total_trades = 0
last_trade_round = -999
loss_streak = 0
cooldown = 0
next_signal = None

# ===== Helpers =====
def calc_recent_trend(window):
    hits = []
    profits = []
    for r in engine[-20:]:
        if r["window"] == window and r["hit"] is not None:
            hits.append(r["hit"])
            profits.append(r["profit_change"])
    if len(hits) < 5:
        return None
    return np.mean(hits), sum(profits)

# ================= MAIN LOOP =================
for i, n in enumerate(numbers):
    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    window_used = None
    wr = None
    ev = None
    profit_change = 0

    # ===== COOLDOWN =====
    if cooldown > 0:
        cooldown -= 1
        state = "COOLDOWN"

    # ===== EXECUTE TRADE =====
    elif next_signal is not None:
        predicted = next_signal["group"]
        window_used = next_signal["window"]
        wr = next_signal["wr"]
        ev = next_signal["ev"]

        hit = 1 if predicted == g else 0
        profit_change = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit += profit_change
        total_trades += 1

        if hit == 0:
            loss_streak += 1
            if loss_streak >= 3:
                cooldown = COOLDOWN_AFTER_LOSS
        else:
            loss_streak = 0

        state = "TRADE"
        last_trade_round = i
        next_signal = None

    # ===== GENERATE SIGNAL =====
    if state == "SCAN" and i - last_trade_round >= BASE_GAP:

        best = None
        best_score = -999

        for w in WINDOWS:
            hits = []
            start = max(w, len(engine) - LOOKBACK)

            for j in range(start, len(engine)):
                if j >= w:
                    hits.append(
                        1 if engine[j]["group"] == engine[j-w]["group"] else 0
                    )

            if len(hits) < 10:
                continue

            hr = np.mean(hits)
            ev_val = hr*WIN_PROFIT - (1-hr)*LOSE_LOSS

            trend = calc_recent_trend(w)

            # ===== TURBO UNLOCK =====
            if trend is None:
                if TURBO_MODE and total_trades < WARMUP_TRADES:
                    hr_recent = 0.5
                    pf_recent = 0
                else:
                    continue
            else:
                hr_recent, pf_recent = trend

            # ===== SCORE BY REAL PERFORMANCE =====
            score = (
                hr_recent * 3 +
                pf_recent * 0.2 +
                hr * 2 +
                ev_val * 1.5
            )

            if hr_recent >= MIN_HIT_RATE and ev_val >= MIN_EV and pf_recent >= SOFT_PROFIT_ALLOW:
                if score > best_score:
                    best_score = score
                    best = (w, hr, ev_val)

        if best is not None:
            w, hr, ev_val = best
            g1 = engine[-w]["group"] if len(engine) >= w else None
            if g1 is not None and engine[-1]["group"] != g1:
                next_signal = {
                    "group": g1,
                    "window": w,
                    "wr": hr,
                    "ev": ev_val
                }
                state = "SIGNAL"

    # ===== SAVE HISTORY =====
    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "wr": None if wr is None else round(wr*100,2),
        "ev": None if ev is None else round(ev,3),
        "state": state,
        "profit_change": profit_change,
        "total_profit": round(total_profit,2),
        "loss_streak": loss_streak,
        "cooldown": cooldown
    })

# ================= DASHBOARD =================
st.title("⚡ TURBO TREND PRO v12.1 — REAL TRADE MODE")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr_total = np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr_total*100,2))

st.caption("Turbo Start | Window 8→18 | Trend by REAL HIT + PROFIT | No Repaint")

# ===== SIGNAL =====
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:28px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal['group']}<br>
    Window: {next_signal['window']}<br>
    WR: {round(next_signal['wr']*100,2)}%<br>
    EV: {round(next_signal['ev'],3)}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning trend...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
