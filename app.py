import streamlit as st
import io
import sys
from contextlib import redirect_stdout
import prop_ev  # import your existing model

st.set_page_config(page_title="Prop_EV Analyzer", page_icon="🧠", layout="centered")
st.title("🧠 Prop_EV Analyzer")

st.markdown(
    """
    This tool runs your full Prop_EV model to estimate **matchup-adjusted EV** for any NBA player prop.  
    Enter your details below and tap **Run Model** to see projections and value metrics.
    """
)

# --- User inputs ---
player = st.text_input("Player name (e.g., Devin Booker):")
stat = st.selectbox("Stat type:", ["PTS", "REB", "AST", "REB+AST", "PRA", "FG3M"])
line = st.number_input("Prop line:", value=20.5, step=0.5)
odds = st.number_input("Sportsbook odds (American format):", value=-110, step=5)

run_clicked = st.button("Run Model")

# --- Execute model ---
if run_clicked:
    if player.strip() == "":
        st.warning("Please enter a player name first.")
    else:
        # Capture model output from console
        buffer = io.StringIO()
        sys.stdin = io.StringIO(f"{player}\n{stat}\n{line}\n{odds}\n")
        with redirect_stdout(buffer):
            try:
                prop_ev.main()
            except Exception as e:
                print(f"[Error running model] {e}")
        output = buffer.getvalue()

        # --- Parse output for nicer formatting ---
        st.divider()
        st.subheader(f"📊 Results for {player}")

        # Extract key lines
        lines = output.splitlines()
        info = {}
        for line in lines:
            if "Model Prob" in line:
                info["Model Prob"] = line.split(":")[-1].strip()
            elif "Book Prob" in line:
                info["Book Prob"] = line.split(":")[-1].strip()
            elif "Model Projection" in line:
                info["Projection"] = line.split(":")[-1].strip()
            elif "EV" in line and "per $1" in line:
                info["EV"] = line.split(":")[-1].strip()
            elif "Verdict" in line or "Value" in line:
                info["Verdict"] = line.strip()
            elif "Games" in line:
                info["Games"] = line.split(":")[-1].strip()

        # Display clean cards
        if "Model Prob" in info:
            st.metric("Model Probability", info["Model Prob"])
        if "Book Prob" in info:
            st.metric("Sportsbook Probability", info["Book Prob"])
        if "Projection" in info:
            st.metric("Model Projection", info["Projection"])
        if "EV" in info:
            st.metric("Expected Value", info["EV"])
        if "Games" in info:
            st.caption(f"Games analyzed: {info['Games']}")

        if "Verdict" in info:
            if "Over" in info["Verdict"]:
                st.success(info["Verdict"])
            elif "Under" in info["Verdict"]:
                st.error(info["Verdict"])
            else:
                st.info(info["Verdict"])

        st.divider()
        with st.expander("📜 Full Console Output"):
            st.text(output)
