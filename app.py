import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"
AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9,14]
DELAY_ROUNDS = 2          # cooldown sau khi thua liên tiếp
REENTRY_EV = 0.15         # EV đủ mạnh để bet bồi

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

cooldown = 0
reentry_mode = False

preview_signal = None
preview_window = None
preview_wr = None
preview_ev = None

for i, n in enumerate(numbers):
    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    window_used = None
    rolling_wr = None
    ev_value = None
    reason = ""

    # ========= COOLDOWN =========
    if cooldown > 0:
        cooldown -= 1
        state = "COOLDOWN"
        reason = "Cooling down"

    # ========= EXECUTE TRADE =========
    elif next_signal is not None:
        predicted = next_signal
        window_used = next_window
        rolling_wr = next_wr
        ev_value = next_ev

        hit = 1 if predicted == g else 0
        total_profit += WIN_PROFIT if hit else -LOSE_LOSS

        state = "TRADE"
        reason = f"Trade W{window_used}"

        if hit == 0:
            # ===== RE-ENTRY nếu EV cao =====
            if ev_value > REENTRY_EV and not reentry_mode:
                reentry_mode = True
                next_signal = predicted
                reason += " | RE-ENTRY"
            else:
                cooldown = DELAY_ROUNDS
                reentry_mode = False
                next_signal = None
        else:
            reentry_mode = False
            next_signal = None

    # ========= GENERATE SIGNAL =========
    if next_signal is None and cooldown == 0 and len(engine) >= 40:
        best_window = None
        best_ev = -999
        best_wr = 0

        for w in WINDOWS:
            hits = []
            start = max(w, len(engine)-30)
            for j in range(start, len(engine)):
                if j >= w:
                    hits.append(1 if engine[j]["group"] == engine[j-w]["group"] else 0)

            if len(hits) >= 20:
                wr = np.mean(hits)
                ev = wr * WIN_PROFIT - (1-wr) * LOSE_LOSS
                if ev > best_ev:
                    best_ev = ev
                    best_window = w
                    best_wr = wr

        # ===== PREVIEW =====
        if best_window and best_wr > 0.28:
            preview_signal = engine[-best_window]["group"]
            preview_window = best_window
            preview_wr = round(best_wr*100,2)
            preview_ev = round(best_ev,3)

        # ===== CONFIRM SIGNAL =====
        if best_window and best_wr > 0.29 and best_ev > 0:
            sig = engine[-best_window]["group"]
            if engine[-1]["group"] != sig:
                next_signal = sig
                next_window = best_window
                next_wr = round(best_wr*100,2)
                next_ev = round(best_ev,3)
                state = "SIGNAL"
                reason = f"Window {best_window}"

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
st.title("🎯 AI BETTING ENGINE PRO")

c1, c2, c3 = st.columns(3)
c1.metric("Total Rounds", len(engine))
c2.metric("Total Profit", round(total_profit,2))

hits = [x["hit"] for x in engine if x["hit"] is not None]
wr = np.mean(hits)*100 if hits else 0
c3.metric("Winrate %", round(wr,2))

# ================= PREVIEW =================
if preview_signal:
    st.markdown(f"""
    <div style='padding:15px;background:#444;color:white;border-radius:10px;text-align:center'>
    🔎 PREVIEW SIGNAL: {preview_signal}<br>
    Window: {preview_window}<br>
    WR: {preview_wr}%<br>
    EV: {preview_ev}
    </div>
    """, unsafe_allow_html=True)

# ================= NEXT BET =================
if next_signal:
    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:26px;font-weight:bold'>
    🚨 READY TO BET 🚨<br>
    🎯 NEXT GROUP: {next_signal}<br>
    Window: {next_window}<br>
    WR: {next_wr}%<br>
    EV: {next_ev}
    </div>
    """, unsafe_allow_html=True)

elif cooldown > 0:
    st.warning(f"⏳ COOLDOWN: {cooldown} rounds left")

else:
    st.info("No signal")

# ================= HISTORY =================
st.subheader("History")
hist_df = pd.DataFrame(engine).iloc[::-1]
st.dataframe(hist_df, use_container_width=True)

st.caption("Re-entry after loss if EV strong | Cooldown after 2nd loss")
