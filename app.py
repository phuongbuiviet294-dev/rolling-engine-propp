import pandas as pd
import numpy as np
from scipy.stats import chisquare
from collections import Counter

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


# ---------- DISTRIBUTION TEST ----------

counts=Counter(groups)

print("\nGroup distribution")

for g in range(1,5):

    print(g,counts[g])


expected=[len(groups)/4]*4
observed=[counts[1],counts[2],counts[3],counts[4]]

chi,p=chisquare(observed,expected)

print("\nChi-square p-value:",p)


# ---------- TRANSITION MATRIX ----------

matrix=np.zeros((4,4))

for i in range(len(groups)-1):

    a=groups[i]-1
    b=groups[i+1]-1

    matrix[a][b]+=1


print("\nTransition matrix")

for i in range(4):

    row=matrix[i]/matrix[i].sum()

    print("from",i+1,row.round(3))


# ---------- SERIAL CORRELATION ----------

g=np.array(groups)

corr=np.corrcoef(g[:-1],g[1:])[0,1]

print("\nLag1 correlation:",round(corr,4))


# ---------- ENTROPY ----------

pvals=np.array(list(counts.values()))/len(groups)

entropy=-(pvals*np.log2(pvals)).sum()

print("\nEntropy:",round(entropy,4))

print("Max entropy:",np.log2(4))


# ---------- RUN LENGTH ----------

runs=[]
current=1

for i in range(1,len(groups)):

    if groups[i]==groups[i-1]:
        current+=1
    else:
        runs.append(current)
        current=1

runs.append(current)

print("\nMax run:",max(runs))
print("Average run:",round(np.mean(runs),2))
