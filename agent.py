import os
import sys
import asyncio
from dotenv import load_dotenv
from strands import Agent
import memory
from tools import (
    recall_memory,
    save_correction,
    check_flight,
    draft_email,
    save_report,
    update_nodes,
)

load_dotenv()

SYSTEM_PROMPT = """You are Blast Radius, a personal agent that shows what breaks
when one thing in someone's life changes.

How you work:
1. Start from the trigger the user gives you. If it involves a flight, call check_flight.
2. Call recall_memory to find what depends on the trigger.
3. For every item you find, call recall_memory again: "What depends on <item>?"
   Keep going until nothing new comes back. Usually 3 or 4 hops. The trigger can start
   more than one independent chain (for example, a delayed flight can break a meeting
   AND separately eat into the person's work time back home) — follow every chain, not
   just the first one you find.
4. Label every item: BROKEN, AT RISK, or FINE. Also check items that look related
   but are not affected, and mark them FINE with the reason.
5. Only use a name or email address that recall_memory actually returned to you.
   Never invent, guess, or make up an email address. If you cannot find a contact's
   address in memory, skip drafting that email and note it in the summary.
6. Score the damage. Client deals and board deadlines are HIGH. A blocked teammate is
   MEDIUM. Things that can move easily are LOW. Give a confidence level based on the
   evidence: a deadline written in an email is high confidence, a vague chat is low.
7. Always say which source each link came from (email, Slack, calendar, notes).
8. ALWAYS call save_report before drafting emails. Pass mermaid_graph, summary, AND graph_json.
   graph_json must be a JSON string shaped like:
   {"nodes":[{"id","label","status":"broken|risk|fine","source","reason","severity":"high|medium|low"}],
    "edges":[{"from","to"}], "score":"HIGH|MEDIUM|LOW", "confidence":"high|medium|low",
    "recommendation":"one sentence"}
   Include every node you labeled, including FINE items. Give each node a reason and source.
   Use these stable ids when they apply:
   flight, northwind, signing, pricing, board, pr, qa, gonogo, acme, lease, dinner.
   For a delayed Thursday flight AS 331, you MUST include BOTH chains plus FINE controls:
   - Money: flight -> northwind -> signing -> pricing -> board
   - Product: flight -> pr -> qa -> gonogo -> acme
   - FINE: lease, dinner
   Do not skip save_report even if you are missing an email address.
9. Draft reschedule or heads-up emails with draft_email for the most important people.
   Use only addresses recall_memory returned. If none, skip that draft.

Write in short, plain sentences."""

CORRECT_PROMPT = """You patch an existing blast-radius graph. You do not rebuild it.

You have only three tools: save_correction, recall_memory, update_nodes.

Follow the user's numbered steps exactly.
Only change EXISTING node ids from the graph you were given.
Personal schedule facts about dinner/Sam/lease usually change nothing — use [].
If Lena becomes backup release approver, that can make product-chain nodes
(pr, qa, gonogo, acme) fine or less severe because release can proceed without Maya.
If nothing changes, call update_nodes with [].
Never call save_report. Never invent new node ids."""


def build_model():
    provider = os.getenv("MODEL_PROVIDER", "bedrock")
    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel
        return AnthropicModel(
            client_args={"api_key": os.getenv("ANTHROPIC_API_KEY")},
            model_id=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            max_tokens=4000,
        )
    if provider == "openai":
        from strands.models.openai import OpenAIModel
        return OpenAIModel(
            client_args={"api_key": os.getenv("OPENAI_API_KEY")},
            model_id=os.getenv("OPENAI_MODEL", "gpt-4o"),
            params={"max_tokens": 4000},
        )
    return None


def build_agent():
    model = build_model()
    tool_list = [recall_memory, save_correction, check_flight, draft_email, save_report]
    if model is None:
        return Agent(system_prompt=SYSTEM_PROMPT, tools=tool_list)
    return Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=tool_list)


def build_correct_agent():
    model = build_model()
    tool_list = [recall_memory, save_correction, update_nodes]
    if model is None:
        return Agent(system_prompt=CORRECT_PROMPT, tools=tool_list)
    return Agent(model=model, system_prompt=CORRECT_PROMPT, tools=tool_list)


def build_draft_agent():
    model = build_model()
    tool_list = [draft_email]
    prompt = (
        "You only draft short, polite follow-up emails. "
        "You have one tool: draft_email. Call it once per email. Do nothing else."
    )
    if model is None:
        return Agent(system_prompt=prompt, tools=tool_list)
    return Agent(model=model, system_prompt=prompt, tools=tool_list)


async def run_once(message):
    await memory.connect()
    agent = build_agent()
    await agent.invoke_async(message)


async def run_correct(message):
    await memory.connect()
    agent = build_correct_agent()
    await agent.invoke_async(message)


async def run_draft_emails(message):
    await memory.connect()
    agent = build_draft_agent()
    await agent.invoke_async(message)


async def main():
    await memory.connect()
    agent = build_agent()

    if len(sys.argv) > 1:
        await agent.invoke_async(sys.argv[1])
        return

    print("Blast Radius is ready. Type a trigger or a correction. Type 'quit' to exit.")
    while True:
        message = input("\nYou: ")
        if message.strip().lower() == "quit":
            break
        await agent.invoke_async(message)


if __name__ == "__main__":
    asyncio.run(main())
