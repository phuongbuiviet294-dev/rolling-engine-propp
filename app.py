import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from scipy.stats import entropy

st.set_page_config(page_title="V10000 RNG Deep Forensics",layout="wide")

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# --------------------
# LOAD DATA
# --------------------

@st.cache_data
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower().strip() for c in df.columns]
    nums=df["number"].dropna().astype(int)
    return nums

numbers=load().values
n=len(numbers)

st.title("🔬 V10000 RNG Deep Forensics")

st.write("Total outputs:",n)

# --------------------
# ENTROPY TEST
# --------------------

st.header("Global Entropy Test")

counts=np.bincount(numbers)[1:]
probs=counts/np.sum(counts)

H=entropy(probs,base=2)

st.metric("Entropy",round(H,4))

theoretical=np.log2(12)

st.write("Theoretical entropy:",round(theoretical,4))

if H<theoretical*0.95:
    
    st.error("Entropy too low")
    
else:
    
    st.success("Entropy looks normal")

# --------------------
# SLIDING ENTROPY
# --------------------

st.header("Sliding Window Entropy")

window=200

Hs=[]
xs=[]

for i in range(0,n-window):

    chunk=numbers[i:i+window]

    c=np.bincount(chunk)[1:]
    
    p=c/np.sum(c)

    Hs.append(entropy(p,base=2))
    
    xs.append(i)

df=pd.DataFrame({
    
    "round":xs,
    "entropy":Hs
    
})

fig=px.line(df,x="round",y="entropy")

st.plotly_chart(fig,use_container_width=True)

# --------------------
# SEGMENT DISTRIBUTION
# --------------------

st.header("Segment Distribution Drift")

segments=5

size=n//segments

rows=[]

for i in range(segments):

    seg=numbers[i*size:(i+1)*size]

    counts=np.bincount(seg)[1:]
    
    probs=counts/np.sum(counts)

    for num,p in enumerate(probs,1):
        
        rows.append({
            
            "segment":i,
            "number":num,
            "prob":p
            
        })

df2=pd.DataFrame(rows)

fig2=px.bar(df2,x="number",y="prob",color="segment",barmode="group")

st.plotly_chart(fig2,use_container_width=True)

# --------------------
# LONG RUN DETECTION
# --------------------

st.header("Long Run Detection")

runs=[]

run_len=1

for i in range(1,n):

    if numbers[i]==numbers[i-1]:
        
        run_len+=1
        
    else:
        
        runs.append(run_len)
        
        run_len=1

max_run=max(runs)

st.metric("Max identical run",max_run)

if max_run>10:
    
    st.warning("Suspicious long run")

else:
    
    st.success("Runs look normal")

# --------------------
# FORENSICS SCORE
# --------------------

st.header("Forensics Score")

score=100

score-=abs(theoretical-H)*20

score-=max_run

score=max(score,0)

st.metric("RNG Integrity Score",round(score,2))

if score>90:
    
    st.success("RNG appears cryptographically strong")

elif score>70:
    
    st.warning("Possible RNG weakness")

else:
    
    st.error("RNG integrity compromised")
