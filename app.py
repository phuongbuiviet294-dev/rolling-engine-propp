import streamlit as st
import pandas as pd
import time

# ================= CONFIG ================= #

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOCK_ROUNDS = 18
AUTO_REFRESH_SECONDS = 5

# ================= FUNCTIONS ================= #

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

def hits_26(data, w):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    return sum(
        1 for i in range(w, 26)
        if recent[i]["group"] == recent[i-w]["group"]
    )

def streak(data, w):
    s = 0
    i = len(data) - 1
    while i - w >= 0:
        if data[i]["group"] == data[i-w]["group"]:
            s += 1
            i -= 1
        else:
            break
    return s

def winrate_26(data):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    hits = [d["hit"] for d in recent if d["hit"] is not None]
    if not hits:
        return 0
    return sum(hits)/len(hits)*100

def score_window(data, w):
    h = hits_26(data, w)
    s = streak(data, w)
    if h < 5:
        return 0
    return (h * 1.2) + (s * 2) + (winrate_26(data)/10)

def scan_best(data):
    best_score = 0
    best_w = None
    for w in range(6,20):
        sc = score_window(data, w)
        if sc > best_score:
            best_score = sc
            best_w = w
    return best_w

# ================= LOAD DATA ================= #

@st.cache_data(ttl=AUTO_REFRESH_SECONDS)
def load_data():
    return pd.read_csv(GOOGLE_SHEET_CSV)

try:
    df_raw = load_data()
except:
    st.error("Không đọc được Google Sheet. Kiểm tra quyền chia sẻ.")
    st.stop()

if df_raw.empty:
    st.warning("Sheet chưa có dữ liệu.")
    st.stop()

# ================= ENGINE PROCESS ================= #

engine_data = []
lock_window = None
lock_remaining = 0

for index, row in df_raw.iterrows():

    n = int(row["number"])
    group = get_group(n)

    predicted = None
    hit = None

    if lock_window:

        if len(engine_data) >= lock_window:
            predicted = engine_data[-lock_window]["group"]
            hit = 1 if predicted == group else 0

        lock_remaining -= 1

        if lock_remaining <= 0:
            lock_window = None

    if not lock_window:
        best_w = scan_best(engine_data)
        if best_w:
            lock_window = best_w
            lock_remaining = LOCK_ROUNDS

    engine_data.append({
        "round": index+1,
        "number": n,
        "group": group,
        "predicted": predicted,
        "hit": hit,
        "window": lock_window
    })

# ================= DASHBOARD ================= #

st.title("🚀 Rolling Engine LIVE MODE")

st.metric("Tổng vòng", len(engine_data))
st.metric("Active Window", lock_window)
st.metric("Lock Remaining", lock_remaining)
st.metric("Winrate 26", round(winrate_26(engine_data),2))

# ================= NEXT GROUP ================= #

next_group = None

if lock_window and len(engine_data) >= lock_window:
    next_group = engine_data[-lock_window]["group"]

if next_group:
    st.markdown(
        f"""
        <div style='padding:15px;
                    background-color:#1f4e79;
                    color:white;
                    border-radius:10px;
                    text-align:center;
                    font-size:28px;
                    font-weight:bold'>
            🎯 NEXT PREDICTED GROUP: {next_group}
        </div>
        """,
        unsafe_allow_html=True
    )

# ================= HISTORY ================= #

df_engine = pd.DataFrame(engine_data)

def highlight_row(row):
    style = [""] * len(row)
    if row.name == df_engine.index[-1]:
        style = ["background-color:#2e7d32;color:white"] * len(row)
    if row["hit"] == 1:
        style[df_engine.columns.get_loc("hit")] = "background-color:green;color:white"
    return style

st.subheader("History")

st.dataframe(
    df_engine.style.apply(highlight_row, axis=1),
    use_container_width=True
)

st.caption(f"Auto refresh mỗi {AUTO_REFRESH_SECONDS} giây")
