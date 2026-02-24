import streamlit as st
import pandas as pd

st.set_page_config(page_title="Rolling Engine PRO++", layout="wide")

# ------------------ ENGINE CORE ------------------ #

class RollingEngine:
    def __init__(self):
        self.history = []
        self.state = "WAIT_26"
        self.lock_window = None
        self.lock_remaining = 0
        self.predicted_group = None
        self.current_streak = 0

    def get_group(self, number):
        if number <= 3:
            return 1
        elif number <= 6:
            return 2
        elif number <= 9:
            return 3
        else:
            return 4

    def add_number(self, number):
        group = self.get_group(number)
        round_no = len(self.history) + 1

        hit = None

        # Check hit
        if self.predicted_group is not None:
            hit = 1 if group == self.predicted_group else 0
            if hit == 1:
                self.current_streak += 1
            else:
                self.current_streak = 0

        # Add record
        record = {
            "Round": round_no,
            "Number": number,
            "Group": group,
            "Predicted": self.predicted_group,
            "Hit": hit,
            "Streak": self.current_streak,
            "State": self.state,
            "Active_Window": self.lock_window,
            "Lock_Remaining": self.lock_remaining
        }

        self.history.append(record)

        # STATE MACHINE
        if len(self.history) >= 26:

            if self.state == "WAIT_26":
                self.state = "SCAN"

            if self.state == "SCAN":
                self.lock_window = 12  # demo window
                self.lock_remaining = 20
                self.predicted_group = group
                self.state = "NEW_LOCK"

            elif self.state == "NEW_LOCK":
                self.state = "LOCKED"

            elif self.state == "LOCKED":
                self.lock_remaining -= 1
                if self.lock_remaining <= 0:
                    self.state = "WAIT_26"
                    self.lock_window = None
                    self.predicted_group = None

        return record


# ------------------ STREAMLIT UI ------------------ #

st.title("🚀 Rolling Engine PRO++")
st.caption("Analytics Full Version – 20 Round Lock")

if "engine" not in st.session_state:
    st.session_state.engine = RollingEngine()

engine = st.session_state.engine

col1, col2 = st.columns([3,1])

with col1:
    number = st.number_input("Nhập số (1-12)", min_value=1, max_value=12, step=1)

with col2:
    if st.button("ADD"):
        engine.add_number(number)

if st.button("RESET"):
    st.session_state.engine = RollingEngine()
    st.experimental_rerun()

st.divider()

st.subheader("📊 Engine Status")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Rounds", len(engine.history))
c2.metric("State", engine.state)
c3.metric("Active Window", engine.lock_window)
c4.metric("Lock Remaining", engine.lock_remaining)

st.divider()

st.subheader("📜 History")

if engine.history:
    df = pd.DataFrame(engine.history)
    st.dataframe(df, use_container_width=True)
else:
    st.write("Chưa có dữ liệu.")
