import os
import asyncio
import streamlit as st
from dotenv import load_dotenv
from strands import Agent
import memory
from tools import recall_memory, save_correction, check_flight, draft_email, save_report
from agent import SYSTEM_PROMPT, build_model

load_dotenv()

st.set_page_config(page_title="Blast Radius", layout="wide")
st.title("Blast Radius")
st.write("What breaks when one thing in your life changes.")

if "connected" not in st.session_state:
    asyncio.run(memory.connect())
    st.session_state["connected"] = True

if "agent" not in st.session_state:
    model = build_model()
    tools = [recall_memory, save_correction, check_flight, draft_email, save_report]
    if model is None:
        st.session_state["agent"] = Agent(system_prompt=SYSTEM_PROMPT, tools=tools)
    else:
        st.session_state["agent"] = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=tools)

agent = st.session_state["agent"]

st.subheader("What changed?")
trigger = st.text_input(
    "Trigger",
    placeholder="My Thursday flight AS 331 is delayed 5 hours. What breaks?",
)
if st.button("Check blast radius"):
    if trigger.strip() != "":
        with st.spinner("Walking the chain..."):
            asyncio.run(agent.invoke_async(trigger))
        st.success("Done. See the report below.")

st.subheader("Correct something")
correction = st.text_input(
    "Correction",
    placeholder="Lena is now approved as backup release approver.",
)
if st.button("Save correction and redo"):
    if correction.strip() != "":
        with st.spinner("Saving correction and redoing the analysis..."):
            asyncio.run(agent.invoke_async(correction))
        st.success("Correction saved. See the updated report below.")

st.subheader("Report")
report_path = os.path.join("reports", "blast_radius.html")
if os.path.exists(report_path):
    with open(report_path, "r") as f:
        html = f.read()
    st.components.v1.html(html, height=700, scrolling=True)
else:
    st.write("No report yet. Enter a trigger above and click Check blast radius.")

st.subheader("Drafted emails")
outbox_files = sorted(os.listdir("outbox"))
if len(outbox_files) == 0:
    st.write("No drafts yet.")
for file_name in outbox_files:
    path = os.path.join("outbox", file_name)
    with open(path, "r") as f:
        content = f.read()
    with st.expander(file_name):
        st.text(content)
