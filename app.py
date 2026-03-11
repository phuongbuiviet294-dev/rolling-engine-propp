================= BALANCED LIVE BETTING ENGINE =================

CÂN BẰNG: Profit ổn định + giảm chuỗi thua + không repaint

import streamlit as st import pandas as pd import numpy as np

================= CONFIG =================

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv" AUTO_REFRESH = 5 WIN_PROFIT = 2.5 LOSE_LOSS = 1 WINDOWS = [9, 15]

Balanced thresholds

MIN_WR = 0.28          # dễ vào hơn turbo-safe MIN_EV = -0.02         # cho phép EV hơi âm nhẹ BASE_GAP = 4           # chống spam LOSS_COOLDOWN = 2      # nghỉ sau chuỗi thua

st.set_page_config(layout="wide")

================= GROUP =================

def get_group(n): if 1 <= n <= 3: return 1 if 4 <= n <= 6: return 2 if 7 <= n <= 9: return 3 if 10 <= n <= 12: return 4 return None

================= LOAD =================

@st.cache_data(ttl=AUTO_REFRESH) def load(): return pd.read_csv(GOOGLE_SHEET_CSV)

try: df = load() except: st.error("Load data failed") st.stop()

if df.empty or "number" not in df.columns: st.error("No data") st.stop()

numbers = df["number"].dropna().astype(int).tolist()

================= ENGINE =================

def run_engine(lookback=26): engine = [] total_profit = 0.0

last_trade_round = -999
loss_streak = 0
cooldown_until = -1

next_signal = None
next_window = None
next_wr = None
next_ev = None

for i, n in enumerate(numbers):
    g = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"
    window_used = None
    wr_used = None
    ev_used = None

    # ===== EXECUTE =====
    if next_signal is not None:
        predicted = next_signal
        window_used = next_window
        wr_used = next_wr
        ev_used = next_ev

        hit = 1 if predicted == g else 0
        if hit:
            total_profit += WIN_PROFIT
            loss_streak = 0
        else:
            total_profit -= LOSE_LOSS
            loss_streak += 1

        if loss_streak >= LOSS_COOLDOWN:
            cooldown_until = i + BASE_GAP

        state = "TRADE"
        last_trade_round = i
        next_signal = None

    # ===== GENERATE =====
    gap_ok = (i - last_trade_round) > BASE_GAP
    cooldown_ok = i > cooldown_until
    enough_data = len(engine) >= 40

    if enough_data and gap_ok and cooldown_ok:
        best_w = None
        best_ev = -999
        best_wr = 0

        for w in WINDOWS:
            hits = []
            start = max(w, len(engine) - lookback)
            for j in range(start, len(engine)):
                if j >= w:
                    hits.append(1 if engine[j]["group"] == engine[j-w]["group"] else 0)

            if len(hits) >= 20:
                wr = np.mean(hits)
                ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                if ev > best_ev:
                    best_ev = ev
                    best_wr = wr
                    best_w = w

        if best_w is not None and best_wr >= MIN_WR and best_ev >= MIN_EV:
            g1 = engine[-best_w]["group"]
            if engine[-1]["group"] != g1:
                next_signal = g1
                next_window = best_w
                next_wr = best_wr
                next_ev = best_ev
                state = "SIGNAL"

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "wr": None if wr_used is None else round(wr_used*100,2),
        "ev": None if ev_used is None else round(ev_used,3),
        "profit": round(total_profit,2),
        "loss_streak": loss_streak,
        "state": state
    })

return total_profit, engine, next_signal, next_window, next_wr, next_ev

================= RUN =================

profit, engine, next_signal, next_window, next_wr, next_ev = run_engine()

================= UI =================

st.title("⚖️ BALANCED LIVE BETTING ENGINE")

c1, c2, c3 = st.columns(3) c1.metric("Rounds", len(engine)) c2.metric("Live Profit", round(profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None] wr = np.mean(hits) if hits else 0 c3.metric("Winrate %", round(wr*100,2))

st.caption(f"Balanced Mode | Windows={WINDOWS} | Lookback=26 | Gap={BASE_GAP} | Cooldown={LOSS_COOLDOWN}")

================= SIGNAL =================

if next_signal is not None: st.markdown(f""" <div style='padding:20px;background:#2e7d32;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'> ✅ READY TO BET<br> 🎯 NEXT GROUP: {next_signal}<br> Window: {next_window}<br> WR: {round(next_wr*100,2)}%<br> EV: {round(next_ev,3)} </div> """, unsafe_allow_html=True) else: st.info("Scanning... Waiting balanced signal")

================= HISTORY =================

st.subheader("Live History (No Repaint)") hist_df = pd.DataFrame(engine).iloc[::-1] st.dataframe(hist_df, use_container_width=True)
