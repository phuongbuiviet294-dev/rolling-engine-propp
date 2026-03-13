import pandas as pd
import numpy as np
from collections import defaultdict

URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(URL)

numbers = df["number"].dropna().astype(int).values

def group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4

groups = np.array([group(x) for x in numbers])

WINDOW = 9

hits = []

for i in range(WINDOW,len(groups)):
    
    pred = groups[i-WINDOW]
    
    hit = 1 if groups[i]==pred else 0
    
    hits.append(hit)

hits = np.array(hits)

results = []

for w in range(6,51):

    patterns = defaultdict(lambda:[0,0])

    for i in range(w,len(hits)-1):

        pattern = tuple(hits[i-w:i])

        next_hit = hits[i]

        patterns[pattern][0]+=1
        patterns[pattern][1]+=next_hit

    for p,v in patterns.items():

        count = v[0]
        wins = v[1]

        if count>20:

            wr = wins/count

            results.append((w,p,count,wr))

results = sorted(results,key=lambda x:x[3],reverse=True)

for r in results[:20]:

    print(r)
