import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9, 15]

BLOCK_SIZE = 600      # độ dài mỗi vùng
BLOCK_STEP = 200      # trượt vùng
MIN_TRADES = 25       # đủ mẫu mới tính
BALANCED_EV_THRESHOLD = -0.02   # Balanced: cho phép EV hơi âm để giữ nhịp lệnh

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
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

df = load()
if df.empty or "number" not in df.columns:
    st.error("Data lỗi hoặc thiếu cột 'number'")
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= CORE ENGINE =================
def simulate_segment(nums, LOOKBACK, GAP, WINDOW):
    profit = 0
    last_trade = -999
    trades = 0

    hist_groups = []

    for i, n in enumerate(nums):
        g = get_group(n)
        hist_groups.append(g)

        if i < max(LOOKBACK, WINDOW):
            continue

        if i - last_trade <= GAP:
            continue

        # tính winrate gần nhất
        recent_hits = []
        start = max(WINDOW, len(hist_groups) - LOOKBACK)

        for j in range(start, len(hist_groups)):
            if j >= WINDOW:
                recent_hits.append(1 if hist_groups[j] == hist_groups[j-WINDOW] else 0)

        if len(recent_hits) < MIN_TRADES:
            continue

        wr = np.mean(recent_hits)
        ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

        if ev < BALANCED_EV_THRESHOLD:
            continue

        pred = hist_groups[-WINDOW]
        actual = g

        hit = 1 if pred == actual else 0
        profit += WIN_PROFIT if hit else -LOSE_LOSS
        trades += 1
        last_trade = i

    return profit, trades

# ================= FIND BEST LOCK ZONE =================
best_score = -999
best_cfg = None

N = len(numbers)

for start in range(max(0, N - 2400), N - BLOCK_SIZE, BLOCK_STEP):
    end = start + BLOCK_SIZE
    segment = numbers[start:end]

    for WINDOW in WINDOWS:
        for LOOKBACK in range(18, 28):
            for GAP in range(3, 5):

                profit, trades = simulate_segment(segment, LOOKBACK, GAP, WINDOW)

                if trades < MIN_TRADES:
                    continue

                # ưu tiên vùng gần hiện tại
                recency_weight = 1 + (end / N)

                score = profit * recency_weight

                if score > best_score:
                    best_score = score
                    best_cfg = (start, end, WINDOW, LOOKBACK, GAP, profit)

if best_cfg is None:
    st.error("Không tìm được vùng profit tốt")
    st.stop()

lock_start, lock_end, WINDOW, LOOKBACK, GAP, lock_profit = best_cfg

# ================= LIVE ENGINE =================
engine = []
total_profit = 0
last_trade = -999
next_signal = None

groups = []

for i, n in enumerate(numbers):
    g = get_group(n)
    groups.append(g)

    predicted = None
    hit = None
    state = "SCAN"

    if next_signal is not None:
        predicted = next_signal
        hit = 1 if predicted == g else 0
        pnl = WIN_PROFIT if hit else -LOSE_LOSS
        total_profit += pnl
        state = "TRADE"
        last_trade = i
        next_signal = None

    if i >= lock_end and i - last_trade > GAP and len(groups) > LOOKBACK:
        recent_hits = []
        start = max(WINDOW, len(groups) - LOOKBACK)

        for j in range(start, len(groups)):
            if j >= WINDOW:
                recent_hits.append(1 if groups[j] == groups[j-WINDOW] else 0)

        if len(recent_hits) >= MIN_TRADES:
            wr = np.mean(recent_hits)
            ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

            if ev >= BALANCED_EV_THRESHOLD:
                pred = groups[-WINDOW]
                if groups[-1] != pred:
                    next_signal = pred
                    state = "SIGNAL"

    engine.append({
        "round": i+1,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state,
        "total_profit": round(total_profit,2)
    })

# ================= DASHBOARD =================
st.title("⚖️ ROLLING MAX PROFIT LOCK — BALANCED")

c1,c2,c3 = st.columns(3)
c1.metric("Total Rounds", len(engine))
c2.metric("Lock Profit", round(lock_profit,2))
c3.metric("Live Profit", round(total_profit,2))

st.caption(f"""
LOCK ZONE: {lock_start} → {lock_end}  
WINDOW={WINDOW} | LOOKBACK={LOOKBACK} | GAP={GAP}
""")

if next_signal:
    st.success(f"🎯 NEXT GROUP: {next_signal}")
else:
    st.info("Scanning...")

# ================= HISTORY =================
st.subheader("Live History")
hist = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist, use_container_width=True)
