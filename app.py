import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = list(range(8,19))   # 8 → 18
BASE_GAP = 2
LOOKBACK = 26
RECENT_N = 50

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
last_trade_round = -999

next_signal = None
next_window = None
gap = BASE_GAP

for i, n in enumerate(numbers):
    g = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"
    window_used = None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted = next_signal
        window_used = next_window
        hit = 1 if predicted == g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS
        state = "TRADE"
        last_trade_round = i
        next_signal = None

    # ===== REAL PERFORMANCE CHECK =====
    recent_trades = [x for x in engine if x["hit"] is not None][-RECENT_N:]
    recent_hits = [x["hit"] for x in recent_trades]

    if recent_hits:
        recent_profit = sum(WIN_PROFIT if h else -LOSE_LOSS for h in recent_hits)
        recent_wr = np.mean(recent_hits)
    else:
        recent_profit = 0
        recent_wr = 0

    loss_streak = 0
    for h in reversed(recent_hits):
        if h == 0:
            loss_streak += 1
        else:
            break

    HARD_STOP = recent_profit <= -15 or loss_streak >= 5
    SOFT_LOCK = recent_profit <= -8

    gap = BASE_GAP + 2 if SOFT_LOCK else BASE_GAP

    # ===== SIGNAL ENGINE =====
    if (
        not HARD_STOP
        and len(engine) >= LOOKBACK
        and i - last_trade_round > gap
    ):
        candidates = []

        for w in WINDOWS:
            hits = []
            start = max(w, len(engine) - LOOKBACK)
            for j in range(start, len(engine)):
                if j >= w:
                    hits.append(
                        1 if engine[j]["group"] == engine[j - w]["group"] else 0
                    )

            if len(hits) >= 15:
                wr = np.mean(hits)
                profit = sum(WIN_PROFIT if h else -LOSE_LOSS for h in hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                # ✅ CHỈ GIỮ WINDOW ĐANG CHẠY TỐT GẦN ĐÂY
                if profit > 0 and wr >= 0.34:
                    candidates.append((profit, wr, ev, w))

        if candidates:
            candidates.sort(reverse=True)
            _, wr, ev, best_w = candidates[0]

            g1 = engine[-best_w]["group"]
            if engine[-1]["group"] != g1:
                next_signal = g1
                next_window = best_w
                state = "SIGNAL"

    engine.append({
        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "state": state,
        "total_profit": round(total_profit,1),
        "recent_profit": round(recent_profit,1),
        "loss_streak": loss_streak,
    })

# ================= UI =================
st.title("🧠 TREND MASTER — REAL PERFORMANCE LOCK PRO")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds", len(engine))
c2.metric("Total Profit", round(total_profit,1))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits) if hits else 0
c3.metric("Winrate %", round(wr*100,2))

st.caption(f"Window 8→18 | Lookback={LOOKBACK} | Gap={gap}")

# ===== STATUS =====
if HARD_STOP:
    st.error("🛑 HARD STOP — Market bad, trading paused")
elif SOFT_LOCK:
    st.warning("⚠️ SOFT LOCK — Reducing trade frequency")
elif next_signal is not None:
    st.success(f"🚨 READY TO BET — NEXT GROUP: {next_signal}")
else:
    st.info("Scanning trend...")

# ===== HISTORY =====
st.subheader("Live History (No Repaint)")
hist = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist, use_container_width=True)
