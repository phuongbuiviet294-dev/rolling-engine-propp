import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOW_RANGE = range(2,10)
LOOKBACK_RANGE = range(10,60)
GAP_RANGE = range(1,8)

# ================= LOAD DATA =================

df = pd.read_csv(DATA_URL)
df.columns=[c.strip().lower() for c in df.columns]

numbers=df["number"].dropna().astype(int).tolist()

# ================= GROUP =================

def get_group(n):

    if 1<=n<=3:
        return 1
    if 4<=n<=6:
        return 2
    if 7<=n<=9:
        return 3
    if 10<=n<=12:
        return 4

groups=[get_group(n) for n in numbers]

# ================= BACKTEST =================

results=[]

for WINDOW in WINDOW_RANGE:

    for LOOKBACK in LOOKBACK_RANGE:

        for GAP in GAP_RANGE:

            profit=0
            trades=0
            wins=0

            last_trade=-999

            for i in range(LOOKBACK,len(groups)-1):

                if i-last_trade<=GAP:
                    continue

                hist=groups[i-LOOKBACK:i]

                hits=[]

                for j in range(WINDOW,len(hist)):

                    if hist[j]==hist[j-WINDOW]:
                        hits.append(1)
                    else:
                        hits.append(0)

                if len(hits)<10:
                    continue

                wr=np.mean(hits)

                if wr>0.28:

                    g=groups[i-WINDOW]

                    trades+=1
                    last_trade=i

                    if groups[i]==g:
                        profit+=WIN_PROFIT
                        wins+=1
                    else:
                        profit-=LOSE_LOSS

            if trades>0:

                winrate=wins/trades

                results.append({
                    "window":WINDOW,
                    "lookback":LOOKBACK,
                    "gap":GAP,
                    "trades":trades,
                    "winrate":winrate,
                    "profit":profit
                })

# ================= RESULT =================

res=pd.DataFrame(results)

res=res.sort_values("profit",ascending=False)

print("\nTOP 20 STRATEGIES\n")
print(res.head(20))

print("\nBEST STRATEGY\n")
print(res.iloc[0])

print("\nWINRATE CHECK")
print("Required winrate > 0.286 to beat game")
