import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from collections import Counter

st.set_page_config(page_title="V5000 RNG Deep Analyzer",layout="wide")

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# -------------------------
# LOAD DATA
# -------------------------

@st.cache_data
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower().strip() for c in df.columns]
    nums=df["number"].dropna().astype(int)
    return nums

numbers=load()
n=len(numbers)

st.title("🎲 V5000 RNG Deep Analyzer")

st.write("Total rounds:",n)

# -------------------------
# DISTRIBUTION
# -------------------------

st.header("Distribution")

freq=numbers.value_counts().sort_index()
prob=freq/n

df=pd.DataFrame({
    "number":freq.index,
    "count":freq.values,
    "prob":prob.values
})

st.dataframe(df)

fig=px.bar(df,x="number",y="prob")
st.plotly_chart(fig,use_container_width=True)

# -------------------------
# SERIAL TEST
# -------------------------

st.header("Serial Test")

pairs=list(zip(numbers[:-1],numbers[1:]))

pair_counts=Counter(pairs)

serial_df=pd.DataFrame([
    {"pair":str(k),"count":v}
    for k,v in pair_counts.items()
])

st.dataframe(serial_df.head(20))

# -------------------------
# RUN LENGTH
# -------------------------

st.header("Run Length Test")

runs=[]
current=numbers.iloc[0]
length=1

for x in numbers.iloc[1:]:
    
    if x==current:
        length+=1
    else:
        runs.append(length)
        length=1
        current=x

runs.append(length)

run_df=pd.DataFrame({"run_length":runs})

fig2=px.histogram(run_df,x="run_length",nbins=20)

st.plotly_chart(fig2,use_container_width=True)

st.write("Average run:",np.mean(runs))

# -------------------------
# BIT BIAS
# -------------------------

st.header("Bit Bias Test")

bits=[]

for x in numbers:
    
    b=format(x,'04b')
    
    for i,bit in enumerate(b):
        
        bits.append((i,int(bit)))

bit_df=pd.DataFrame(bits,columns=["bit","value"])

bias=bit_df.groupby("bit")["value"].mean()

bias_df=pd.DataFrame({
    
    "bit":bias.index,
    "prob_one":bias.values
    
})

st.dataframe(bias_df)

fig3=px.bar(bias_df,x="bit",y="prob_one")

st.plotly_chart(fig3,use_container_width=True)

# -------------------------
# CYCLE DETECTION
# -------------------------

st.header("Cycle Detection")

seq=numbers.values

cycle=None

for size in range(10,200):
    
    pattern=tuple(seq[-size:])
    
    for i in range(len(seq)-size*2):
        
        if tuple(seq[i:i+size])==pattern:
            
            cycle=size
            
            break
    
    if cycle:
        break

if cycle:
    
    st.success("Cycle detected length:"+str(cycle))

else:
    
    st.write("No cycle found")

# -------------------------
# SPECTRAL TEST
# -------------------------

st.header("Spectral Pattern")

x=numbers[:-1]
y=numbers[1:]

spec_df=pd.DataFrame({
    
    "x":x,
    "y":y
    
})

fig4=px.scatter(spec_df,x="x",y="y")

st.plotly_chart(fig4,use_container_width=True)

# -------------------------
# RANDOMNESS SCORE
# -------------------------

st.header("Randomness Score")

score=100

# distribution check
expected=1/len(freq)
dev=np.abs(prob-expected).mean()

score-=dev*100

# bit bias
bit_dev=np.abs(bias-0.5).mean()

score-=bit_dev*100

score=max(score,0)

st.metric("Randomness Score",round(score,2))

if score>90:
    
    st.success("RNG looks strong")

elif score>70:
    
    st.warning("Possible weak RNG")

else:
    
    st.error("RNG likely exploitable")
