import pandas as pd
from collections import defaultdict
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# ---------- GROUP ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------- LOAD DATA ----------
df=pd.read_csv(DATA_URL)

numbers=df["number"].dropna().astype(int).tolist()

groups=[group(n) for n in numbers]

print("Total rounds:",len(groups))


# ---------- SCAN PATTERNS ----------
def scan(window):

    stats=defaultdict(list)

    for i in range(len(groups)-window):

        state=tuple(groups[i:i+window])
        nxt=groups[i+window]

        stats[state].append(nxt)

    results=[]

    for s,v in stats.items():

        count=len(v)

        if count<40:
            continue

        counts=np.bincount(v)[1:]

        probs=counts/count

        best_group=np.argmax(probs)+1
        best_prob=max(probs)

        edge=best_prob-0.25

        results.append((s,count,best_group,best_prob,edge))

    return results


# ---------- RUN SCAN ----------
all_results=[]

for w in range(2,11):

    r=scan(w)

    for x in r:

        all_results.append((w,)+x)


df_res=pd.DataFrame(all_results,
    columns=["window","pattern","count","predict_group","prob","edge"])


df_res=df_res.sort_values("edge",ascending=False)

print("\nTop patterns:\n")

print(df_res.head(20))


# ---------- CHECK IF PLAYABLE ----------
playable=df_res[df_res["prob"]>0.33]

print("\nPlayable patterns (>33%):\n")

print(playable.head(20))
