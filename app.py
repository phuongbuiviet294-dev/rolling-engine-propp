import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5
WIN_PROFIT = 2.5
LOSE_LOSS = 1
WINDOWS = [6,9,12,14,18,24,32]

MIN_WR = 0.29
MIN_EV = 0.02
REGIME_STD_MIN = 0.46
STREAK_MIN = 2
COOLDOWN_AFTER_LOSS = 2
REENTRY_EV = 0.15

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

next_signal = None
next_window = None
next_wr = None
next_ev = None
signal_created_at = None

cooldown = 0
reentry_pending = False

preview_signal = None
preview_window = None
preview_wr = None
preview_ev = None

def calc_streak(hist):
    s = 0
    for i in range(1, min(6, len(hist))):
        if hist[-i]["group"] == hist[-i-1]["group"]:
            s += 1
        else:
            break
    return s

for i, n in enumerate(numbers):
    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    window_used = None
    rolling_wr = None
    ev_value = None
    reason = None

    # ===== COOLDOWN =====
    if cooldown > 0:
        cooldown -= 1
        state = "COOLDOWN"

    # ===== EXECUTE TRADE =====
    elif next_signal is not None:
        predicted = next_signal
        window_used = next_window
        rolling_wr = next_wr
        ev_value = next_ev

        hit = 1 if predicted == g else 0

        if hit:
            total_profit += WIN_PROFIT
            reentry_pending = False
        else:
            total_profit -= LOSE_LOSS
            cooldown = COOLDOWN_AFTER_LOSS
            if ev_value and ev_value > REENTRY_EV:
                reentry_pending = True

        state = "TRADE"
        reason = f"Trade from round {signal_created_at}"
        next_signal = None

    # ===== RE-ENTRY TRADE =====
    elif reentry_pending:
        predicted = engine[-1]["predicted"]
        hit = 1 if predicted == g else 0

        if hit:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS

        state = "RE-ENTRY"
        reason = "Re-entry after strong EV loss"
        reentry_pending = False

    # ===== GENERATE SIGNAL =====
    if len(engine) >= 40 and cooldown == 0 and next_signal is None and not reentry_pending:
        best_window = None
        best_ev = -999
        best_wr = 0
        best_std = 0

        for w in WINDOWS:
            hits = []
            for j in range(len(engine)-30, len(engine)):
                if j >= w:
                    hits.append(1 if engine[j]["group"] == engine[j-w]["group"] else 0)

            if len(hits) >= 20:
                wr = np.mean(hits)
                ev = wr * WIN_PROFIT - (1-wr) * LOSE_LOSS
                std = np.std(hits)

                if ev > best_ev:
                    best_ev = ev
                    best_window = w
                    best_wr = wr
                    best_std = std

        # ===== PREVIEW =====
        if best_window and best_wr > 0.27:
            preview_signal = engine[-best_window]["group"]
            preview_window = best_window
            preview_wr = round(best_wr*100,2)
            preview_ev = round(best_ev,3)

        # ===== FILTERS =====
        if best_window:
            streak = calc_streak(engine)

            regime_ok = best_std > REGIME_STD_MIN
            streak_ok = streak >= STREAK_MIN
            edge_ok = best_wr > MIN_WR and best_ev > MIN_EV

            if regime_ok and (streak_ok or edge_ok):
                next_signal = engine[-best_window]["group"]
                next_window = best_window
                next_wr = round(best_wr*100,2)
                next_ev = round(best_ev,3)
                signal_created_at = i + 1
                state = "SIGNAL"
                reason = f"Window {best_window} | Regime+Edge"

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "rolling_wr_%": rolling_wr,
        "ev": ev_value,
        "state": state,
        "reason": reason
    })

# ================= DASHBOARD =================
st.title("🚀 AI BETTING ENGINE — PRO MAX PROFIT")

c1,c2,c3 = st.columns(3)
c1.metric("Total Rounds", len(engine))
c2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits)*100 if hits else 0
c3.metric("Winrate %", round(wr,2))

# ================= PREVIEW =================
if preview_signal:
    st.markdown(f"""
    <div style='padding:15px;background:#333;color:white;border-radius:10px;text-align:center'>
    🔎 PREVIEW SIGNAL: <b>{preview_signal}</b><br>
    Window: {preview_window}<br>
    WR: {preview_wr}%<br>
    EV: {preview_ev}
    </div>
    """, unsafe_allow_html=True)

# ================= NEXT BET =================
if next_signal:
    st.markdown(f"""
    <div style='padding:22px;background:#c62828;color:white;border-radius:12px;text-align:center'>
    🚨 READY TO BET 🚨<br><br>
    🎯 NEXT GROUP: <b style='font-size:34px'>{next_signal}</b><br><br>
    Window: {next_window}<br>
    WR: {next_wr}%<br>
    EV: {next_ev}
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("No signal")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)

st.caption("PRO: Regime Filter | Streak | Adaptive Window | Cooldown | Re-entry | Skip Noise")
