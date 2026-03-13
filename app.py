import pandas as pd
import numpy as np
from scipy.stats import chisquare

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)
df.columns=[c.strip().lower() for c in df.columns]

numbers=df["number"].dropna().astype(int)

def group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4

groups=numbers.apply(group)

print("Total rounds:",len(groups))

# frequency
freq=groups.value_counts().sort_index()
print("\nGroup frequency")
print(freq)

print("\nGroup percentage")
print(freq/len(groups)*100)

# chi-square randomness test
expected=[len(groups)/4]*4
chi,p=chisquare(freq,expected)

print("\nChi-square test")
print("Chi2:",chi)
print("p-value:",p)

# transition matrix
print("\nTransition matrix")
trans=np.zeros((4,4))

for i in range(1,len(groups)):
    a=groups.iloc[i-1]-1
    b=groups.iloc[i]-1
    trans[a][b]+=1

print(pd.DataFrame(trans))
