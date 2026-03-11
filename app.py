import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN = 2.5
LOSS = 1
WINDOWS = [9, 15]

TRAIN_MIN = 800
STEP = 200

STOPLOSS_STREAK = 5     # B — dừng khi thua liên tiếp
COOLDOWN_ROUNDS = 25    # nghỉ sau stoploss

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
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    return df

df = load_data()
numbers = df["number"].dropna().astype(int).tolist()

# ================= CORE ENGINE =================
def simulate_live(numbers, LB, GP):
    profit = 0
    equity = []
    hits = []

    last_trade = -999
    next_sig = None
    groups_hist = []

    loss_streak = 0
    cooldown = 0

    for i, n in enumerate(numbers):
        g = get_group(n)
        hit = None
        state = "SCAN"

        # ===== COOLDOWN =====
        if cooldown > 0:
            cooldown -= 1
            groups_hist.append(g)
            equity.append(profit)
            continue

        # ===== EXECUTE =====
        if next_sig is not None:
            hit = 1 if next_sig == g else 0
            profit += WIN if hit else -LOSS
            hits.append(hit)
            state = "TRADE"
            last_trade = i
            next_sig = None

            if hit == 0:
                loss_streak += 1
            else:
                loss_streak = 0

            # ===== STOPLOSS =====
            if loss_streak >= STOPLOSS_STREAK:
                cooldown = COOLDOWN_ROUNDS
                loss_streak = 0

        # ===== SIGNAL =====
        if len(groups_hist) >= 40 and i - last_trade > GP:
            best_ev = -999
            best_w = None
            best_wr = 0

            for w in WINDOWS:
                recent = []
                start = max(w, len(groups_hist) - LB)

                for j in range(start, len(groups_hist)):
                    if j >= w:
                        recent.append(
                            1 if groups_hist[j] == groups_hist[j - w] else 0
                        )

                if len(recent) >= 20:
                    wr = np.mean(recent)
                    ev = wr * WIN - (1 - wr) * LOSS
                    if ev > best_ev:
                        best_ev = ev
                        best_w = w
                        best_wr = wr

            if best_w and best_wr > 0.29:
                if groups_hist[-1] != groups_hist[-best_w]:
                    next_sig = groups_hist[-best_w]
                    state = "SIGNAL"

        groups_hist.append(g)
        equity.append(profit)

    return profit, equity, hits, next_sig

# ================= LOCK BEST CONFIG (C) =================
@st.cache_data(ttl=3600)
def find_best_lock(numbers):
    best_profit = -999
    best_cfg = (26, 4)

    for LB in range(18, 29):
        for GP in range(3, 7):
            p, _, _, _ = simulate_live(numbers[:TRAIN_MIN], LB, GP)
            if p > best_profit:
                best_profit = p
                best_cfg = (LB, GP)

    return best_cfg

LOCK_LB, LOCK_GP = find_best_lock(numbers)

# ================= WALK FORWARD LIVE =================
profit, equity, hits, next_signal = simulate_live(numbers, LOCK_LB, LOCK_GP)

# ================= METRICS =================
peak = max(equity) if equity else 0
cur = equity[-1] if equity else 0
dd = peak - cur

wins = sum(hits)
losses = len(hits) - wins
wr = wins / len(hits) if hits else 0
pf = (wins * WIN) / (losses * LOSS) if losses else 0
exp = wr * WIN - (1 - wr) * LOSS
roi100 = cur / (len(equity)/100) if equity else 0

# ================= UI =================
st.title("🧠 WALK-FORWARD LIVE PRO ENGINE")

c1,c2,c3 = st.columns(3)
c1.metric("Rounds", len(equity))
c2.metric("Net Profit", round(cur,2))
c3.metric("Winrate %", round(wr*100,2))

c4,c5,c6 = st.columns(3)
c4.metric("Peak Profit", round(peak,2))
c5.metric("Max Drawdown", round(dd,2))
c6.metric("ROI / 100 rounds", round(roi100,2))

c7,c8,c9 = st.columns(3)
c7.metric("Profit Factor", round(pf,2))
c8.metric("Expectancy", round(exp,3))
c9.metric("Total Trades", len(hits))

st.caption(f"🔒 Locked Config → Lookback={LOCK_LB} | Gap={LOCK_GP} | Stoploss={STOPLOSS_STREAK} | Cooldown={COOLDOWN_ROUNDS}")

# ================= NEXT SIGNAL (A) =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>
        🚨 READY TO BET 🚨<br>
        🎯 NEXT GROUP: {next_signal}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning... No valid signal")

# ================= EQUITY =================
st.subheader("Equity Curve")
st.line_chart(equity)
