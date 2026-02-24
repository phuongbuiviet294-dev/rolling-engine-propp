import streamlit as st
import pandas as pd

st.set_page_config(page_title="Rolling Engine PRO++", layout="wide")

class RollingEngine:
    def __init__(self):
        self.history = []
        self.state = "WAIT_26"
        self.lock_window = None
        self.lock_remaining = 0
        self.current_streak = 0

    def get_group(self, n):
        if n <= 3: return 1
        if n <= 6: return 2
        if n <= 9: return 3
        return 4

    def hits_26(self, window):
        if len(self.history) < 26:
            return 0

        data = self.history[-26:]
        hits = 0

        for i in range(window, len(data)):
            if data[i]["Group"] == data[i-window]["Group"]:
                hits += 1

        return hits

    def calc_streak(self, window):
        if len(self.history) < window:
            return 0

        streak = 0
        i = len(self.history) - 1

        while i - window >= 0:
            if self.history[i]["Group"] == self.history[i-window]["Group"]:
                streak += 1
                i -= 1
            else:
                break

        return streak

    def scan_best_window(self):
        best_score = 0
        best_window = None

        for w in range(6, 20):
            h = self.hits_26(w)
            if h < 6:
                continue

            s = self.calc_streak(w)
            if s >= 3:
                score = s + h
                if score > best_score:
                    best_score = score
                    best_window = w

        return best_window

    def add(self, number):
        group = self.get_group(number)
        round_no = len(self.history) + 1

        predicted = None
        hit = None

        # -------- PREDICTION -------- #
        if self.lock_window and len(self.history) >= self.lock_window:
            predicted = self.history[-self.lock_window]["Group"]
            hit = 1 if group == predicted else 0

            if hit == 1:
                self.current_streak += 1
            else:
                self.current_streak = 0

        record = {
            "Round": round_no,
            "Number": number,
            "Group": group,
            "Predicted": predicted,
            "Hit": hit,
            "Window_Streak": self.current_streak,
            "State": self.state,
            "Active_Window": self.lock_window,
            "Lock_Remaining": self.lock_remaining
        }

        self.history.append(record)

        # -------- STATE MACHINE -------- #

        if len(self.history) >= 26:

            if self.state == "WAIT_26":
                best = self.scan_best_window()
                if best:
                    self.lock_window = best
                    self.lock_remaining = 20
                    self.state = "NEW_LOCK"

            elif self.state == "NEW_LOCK":
                self.state = "LOCKED"

            elif self.state == "LOCKED":
                self.lock_remaining -= 1
                if self.lock_remaining <= 0:
                    self.state = "WAIT_26"
                    self.lock_window = None
                    self.current_streak = 0

        return record


# ---------------- UI ---------------- #

st.title("🚀 Rolling Engine PRO++")
st.caption("Predicted = Group at i-window | Lock 20 | Scan 1-1-1 + Hits>=6")

if "engine" not in st.session_state:
    st.session_state.engine = RollingEngine()

engine = st.session_state.engine

col1, col2 = st.columns([3,1])

with col1:
    number = st.number_input("Nhập số (1-12)", 1, 12)

with col2:
    if st.button("ADD"):
        engine.add(number)

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
