import streamlit as st
import pandas as pd

# ================= CONFIG ================= #

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

LOCK_ROUNDS = 18
AUTO_REFRESH = 5

# ================= CORE ================= #

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

def volatility_26(data):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    changes = sum(
        1 for i in range(1, 26)
        if recent[i]["group"] != recent[i-1]["group"]
    )
    return round(changes / 25 * 100, 2)

def winrate_26(data):
    if len(data) < 26:
        return 0
    recent = data[-26:]
    hits = [d["hit"] for d in recent if d["hit"] is not None]
    if not hits:
        return 0
    return round(sum(hits)/len(hits)*100,2)

def score_window(data, w):
    h = hits_26(data, w)
    s = streak(data, w)
    if h < 5:
        return 0
    return (h * 1.2) + (s * 2)

def scan_best(data):
    best_score = 0
    best_w = None
    for w in range(6,20):
        sc = score_window(data, w)
        if sc > best_score:
            best_score = sc
            best_w = w
    return best_w

# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load_data():
    return pd.read_csv(GOOGLE_SHEET_CSV)

try:
    df_raw = load_data()
except:
    st.error("Không đọc được Google Sheet.")
    st.stop()

if df_raw.empty:
    st.warning("Sheet chưa có dữ liệu.")
    st.stop()

numbers = df_raw["number"].dropna().astype(int).tolist()

# ================= RESET ĐỘNG ================= #

if "prev_first" not in st.session_state:
    st.session_state.prev_first = None
    st.session_state.prev_len = 0

reset_flag = False

if len(numbers) < st.session_state.prev_len:
    reset_flag = True

if numbers and st.session_state.prev_first != numbers[0]:
    reset_flag = True

if reset_flag:
    st.session_state.prev_first = numbers[0] if numbers else None
    st.session_state.prev_len = len(numbers)
else:
    st.session_state.prev_len = len(numbers)

# ================= ENGINE ================= #

engine_data = []
lock_window = None
lock_remaining = 0

for i, n in enumerate(numbers):

    group = get_group(n)
    predicted = None
    hit = None
    state = "SCAN"

    if lock_window:
        state = "LOCK"

        if len(engine_data) >= lock_window:
            predicted = engine_data[-lock_window]["group"]
            hit = 1 if predicted == group else 0

        lock_remaining -= 1

        if lock_remaining <= 0:
            lock_window = None

    if not lock_window and len(engine_data) >= 26:
        best_w = scan_best(engine_data)
        if best_w:
            lock_window = best_w
            lock_remaining = LOCK_ROUNDS
            state = "LOCK_START"

    engine_data.append({
        "round": i+1,
        "number": n,
        "group": group,
        "predicted": predicted,
        "hit": hit,
        "window": lock_window,
        "state": state
    })

# ================= UI ================= #

st.title("🚀 Rolling Engine PRO++ LIVE")

st.metric("Tổng vòng", len(engine_data))
st.metric("Active Window", lock_window)
st.metric("Lock Remaining", lock_remaining)
st.metric("Winrate 26", winrate_26(engine_data))
st.metric("Volatility 26", volatility_26(engine_data))

# -------- NEXT GROUP -------- #

next_group = None
if lock_window and len(engine_data) >= lock_window:
    next_group = engine_data[-lock_window]["group"]

if next_group:
    st.markdown(
        f"""
        <div style='padding:15px;
                    background:#1f4e79;
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

# -------- HISTORY (Newest First) -------- #

df_engine = pd.DataFrame(engine_data)
df_display = df_engine.iloc[::-1].reset_index(drop=True)

def highlight(row):
    style = [""] * len(row)

    # dòng mới nhất
    if row.name == 0:
        style = ["background-color:#2e7d32;color:white"] * len(row)

    if row["hit"] == 1:
        style[df_display.columns.get_loc("hit")] = "background-color:green;color:white"

    if row["hit"] == 0:
        style[df_display.columns.get_loc("hit")] = "background-color:red;color:white"

    if row["state"] == "LOCK_START":
        style[df_display.columns.get_loc("state")] = "background-color:orange;color:black"

    return style

st.subheader("History (Newest First)")

st.dataframe(
    df_display.style.apply(highlight, axis=1),
    use_container_width=True,
    height=500
)

st.caption(f"Auto refresh mỗi {AUTO_REFRESH} giây | Reset động bật")
