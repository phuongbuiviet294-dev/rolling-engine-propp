import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# =========================
# CONFIG
# =========================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW = 9
LOOKBACK = 26
GAP = 4

WIN = 2.5
LOSS = 1


# =========================
# GROUP
# =========================

def group(n):

    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


# =========================
# LOAD DATA
# =========================

df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int).tolist()

print("Total rounds:", len(numbers))


# =========================
# ENGINE
# =========================

profit = 0
profits = []

engine = []

next_signal = None
last_trade_round = -999

for i, n in enumerate(numbers):

    g = group(n)

    predicted = None
    hit = None
    state = "SCAN"

    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal

        hit = 1 if predicted == g else 0

        if hit == 1:
            profit += WIN
        else:
            profit -= LOSS

        state = "TRADE"

        last_trade_round = i

        next_signal = None

    # ===== SIGNAL GENERATION =====

    if i - last_trade_round > GAP and i > LOOKBACK:

        recent = []

        start = max(WINDOW, i - LOOKBACK)

        for j in range(start, i):

            if j >= WINDOW:

                recent.append(
                    1 if group(numbers[j]) == group(numbers[j - WINDOW]) else 0
                )

        if len(recent) > 10:

            wr = np.mean(recent)

            ev = wr * WIN - (1 - wr) * LOSS

            if ev > 0:

                g1 = group(numbers[i - WINDOW])

                if group(numbers[i - 1]) != g1:

                    next_signal = g1
                    state = "SIGNAL"

    profits.append(profit)

    engine.append({
        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state,
        "profit": profit
    })


# =========================
# STATS
# =========================

peak = max(profits)
final = profits[-1]

print("Peak profit:", peak)
print("Final profit:", final)

hits = [x["hit"] for x in engine if x["hit"] is not None]

wr = np.mean(hits) if hits else 0

print("Trades:", len(hits))
print("Winrate:", wr)


# =========================
# EQUITY CURVE
# =========================

plt.figure(figsize=(12,6))

plt.plot(profits, label="Equity Curve")

plt.axhline(0, linestyle="--")

plt.scatter(profits.index(peak), peak, color="red", label="Peak")

plt.title("Equity Curve (4000 rounds)")
plt.xlabel("Round")
plt.ylabel("Profit")

plt.legend()

plt.show()
