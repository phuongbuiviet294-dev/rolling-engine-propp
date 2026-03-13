import streamlit as st
import pandas as pd
import requests
import io
from collections import Counter, defaultdict

# ================= CONFIG =================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE = 200
WINDOW_RANGE = range(8,18)
LOOKBACK = 26

WIN = 2.5
LOSS = 1

CONF_THRESHOLD = 0.40

st.set_page_config(layout="wide")

# ================= GROUP =================

def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

# ================= LOAD DATA =================

@st.cache_data(ttl=5)
def load():
    try:
        r = requests.get(DATA_URL)
        df = pd.read_csv(io.StringIO(r.text))
        return df["number"].dropna().astype(int).tolist()
    except:
        return []

numbers = load()

if len(numbers) == 0:
    st.error("No data")
    st.stop()

groups = [group(n) for n in numbers]

# ================= PREDICT =================

def predict(data, window):
    seq = data[-window:]
    c = Counter(seq)
    return max(c, key=c.get)

# ================= WINDOW SCAN =================

def scan_windows(data):

    best_window = None
    best_score = -9999

    for w in WINDOW_RANGE:

        equity = 0
        peak = 0
        dd = 0

        for i in range(w, len(data)-1):

            pred = predict(data[:i], w)
            actual = data[i]

            if pred == actual:
                equity += WIN
            else:
                equity -= LOSS

            peak = max(peak, equity)
            dd = max(dd, peak - equity)

        score = equity - dd*0.5

        if score > best_score:
            best_score = score
            best_window = w

    return best_window

# ================= TRAIN =================

best_window = scan_windows(groups[:TRAIN_SIZE])

# ================= ENGINE =================

hits = []
profit = 0
equity_curve = []

trades = 0
wins = 0

pattern_prob = 0
markov_prob = 0
momentum = 0

history = []

for i in range(TRAIN_SIZE, len(groups)-1):

    pred = predict(groups[:i], best_window)
    actual = groups[i]

    hit = 1 if pred == actual else 0
    hits.append(hit)

    # -------- pattern probability --------

    if len(hits) > 50:

        counts = defaultdict(int)
        succ = defaultdict(int)

        for j in range(len(hits)-3):

            pat = tuple(hits[j:j+3])
            nxt = hits[j+3]

            counts[pat] += 1

            if nxt == 1:
                succ[pat] += 1

        best = 0

        for pat in counts:
            prob = succ[pat] / counts[pat]
            if prob > best:
                best = prob

        pattern_prob = best

    # -------- markov --------

    if len(hits) > 20:

        last = hits[-1]
        total = 0
        success = 0

        for j in range(len(hits)-1):

            if hits[j] == last:
                total += 1
                if hits[j+1] == 1:
                    success += 1

        if total > 0:
            markov_prob = success / total

    # -------- momentum --------

    if len(hits) >= LOOKBACK:
        momentum = sum(hits[-LOOKBACK:]) / LOOKBACK

    # -------- signal detection --------

    signal = False

    if len(hits) >= 2 and hits[-2:] == [1,1]:
        signal = True

    if len(hits) >= 3 and hits[-3:] == [1,0,1]:
        signal = True

    if len(hits) >= 4 and hits[-4:] == [0,0,0,0]:
        signal = True

    confidence = (
        0.5 * pattern_prob +
        0.3 * markov_prob +
        0.2 * momentum
    )

    trade = False

    if signal and confidence >= CONF_THRESHOLD:

        trade = True
        trades += 1

        if hit == 1:
            profit += WIN
            wins += 1
        else:
            profit -= LOSS

    equity_curve.append(profit)

    history.append({
        "round": i,
        "pred": pred,
        "actual": actual,
        "hit": hit,
        "confidence": round(confidence,3),
        "signal": signal,
        "trade": trade,
        "profit": profit
    })

wr = wins / trades if trades else 0

# ================= NEXT SIGNAL =================

next_pred = predict(groups, best_window)

confidence = (
    0.5 * pattern_prob +
    0.3 * markov_prob +
    0.2 * momentum
)

# ================= DASHBOARD =================

st.title("⚡ V70 Signal Regime Engine")

col1,col2,col3 = st.columns(3)

col1.metric("Best Window", best_window)
col2.metric("Trades", trades)
col3.metric("Winrate %", round(wr*100,2))

st.metric("Profit", round(profit,2))

st.subheader("Edge Metrics")

st.write("Pattern Prob:", round(pattern_prob,3))
st.write("Markov Prob:", round(markov_prob,3))
st.write("Momentum:", round(momentum,3))
st.write("Confidence:", round(confidence,3))

st.subheader("Next Signal")

if confidence >= CONF_THRESHOLD:
    st.success(f"TRADE → Group {next_pred}")
else:
    st.info(f"WAIT → Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity": equity_curve}))

st.subheader("Recent History")

st.dataframe(pd.DataFrame(history).tail(50), use_container_width=True)
