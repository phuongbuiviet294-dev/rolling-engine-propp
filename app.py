import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1.0
WINDOWS = list(range(9))   # 8 → 18

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
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    return df

df = load_data()

if "number" not in df.columns:
    st.error("Google Sheet phải có cột: number")
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE =================
def run_engine(lookback=26, gap=2):
    history = []
    total_profit = 0
    last_trade_i = -999
    next_signal = None

    for i, n in enumerate(numbers):
        g = get_group(n)
        state = "SCAN"
        hit = None
        pred = None
        window_used = None

        # ===== EXECUTE TRADE =====
        if next_signal is not None:
            pred = next_signal
            hit = 1 if pred == g else 0
            pnl = WIN_PROFIT if hit else -LOSE_LOSS
            total_profit += pnl
            state = "TRADE"
            next_signal = None
            last_trade_i = i
        else:
            pnl = 0

        # ===== GENERATE SIGNAL =====
        if i > 50 and i - last_trade_i >= gap:
            best_w = None
            best_score = -999

            for w in WINDOWS:
                if i - w - lookback < 0:
                    continue

                hits = []
                for j in range(i - lookback, i):
                    if j - w >= 0:
                        g1 = get_group(numbers[j])
                        g2 = get_group(numbers[j - w])
                        hits.append(1 if g1 == g2 else 0)

                if len(hits) < 10:
                    continue

                wr = np.mean(hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS
                score = ev + wr

                if score > best_score:
                    best_score = score
                    best_w = w

            if best_w is not None:
                ref_group = get_group(numbers[i - best_w])
                if ref_group != g:
                    next_signal = ref_group
                    state = "SIGNAL"
                    window_used = best_w

        history.append({
            "round": i + 1,
            "number": n,
            "group": g,
            "predicted": pred,
            "hit": hit,
            "pnl": pnl,
            "window": window_used,
            "state": state,
            "total_profit": round(total_profit, 2)
        })

    return history, total_profit, next_signal

# ================= RUN =================
history, total_profit, next_signal = run_engine()

# ================= DASHBOARD =================
st.title("🚀 TREND ENGINE — LIVE")

c1, c2, c3 = st.columns(3)
c1.metric("Rounds", len(history))
c2.metric("Total Profit", round(total_profit, 2))

hits = [h["hit"] for h in history if h["hit"] is not None]
wr = np.mean(hits) * 100 if hits else 0
c3.metric("Winrate %", round(wr, 2))

# ================= SIGNAL =================
if next_signal is not None:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
                border-radius:12px;text-align:center;font-size:28px;font-weight:bold'>
        🚨 READY TO BET<br>
        🎯 NEXT GROUP: {next_signal}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Scanning market...")

# ================= HISTORY =================
st.subheader("Live History")
hist_df = pd.DataFrame(history).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)
