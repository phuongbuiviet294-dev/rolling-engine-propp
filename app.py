import pandas as pd
import numpy as np

URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(URL)

numbers = df["number"].dropna().astype(int).values

# group function giống code cũ
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

# winrate chung
base_winrate = hits.mean()

# test pattern 1-1
total = 0
wins = 0

for i in range(2,len(hits)):
    
    if hits[i-2]==1 and hits[i-1]==1:
        
        total+=1
        
        if hits[i]==1:
            wins+=1

if total>0:
    pattern_wr = wins/total
else:
    pattern_wr = 0

print("Base winrate:",base_winrate)
print("1-1 cases:",total)
print("Wins after 1-1:",wins)
print("Winrate after 1-1:",pattern_wr)
