# Blast Radius

Engineers ask "what's the blast radius?" before changing production.
Nobody does that for their own life. Blast Radius does.

Tell it what changed ("my Thursday flight is delayed 5 hours") and it walks your
personal knowledge graph to show everything that breaks, how bad it is, and why.
Then it drafts the emails to fix it. Correct it once, and it remembers.

## Stack
- Cognee Cloud: personal memory graph (calendar, email, Slack, notes)
- Bright Data: live public data (flight status)
- AWS Strands Agents: the agent loop that walks the dependency chain
- Docker: runs the agent in an isolated container

## Setup
    python3.11 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env    # fill in keys

## Run
    python ingest.py
    python ask.py "What depends on the Northwind walkthrough?"
    python agent.py "My Thursday flight AS 331 might be delayed. What breaks?"
    python agent.py         # interactive mode for the demo
    streamlit run app.py    # UI: trigger box, correction box, report, email drafts

Open reports/blast_radius.html to see the chain. Drafted emails land in outbox/.

## Demo script
1. "My flight AS 331 on Thursday is delayed 5 hours. What breaks?"
2. Show the report: two chains (Q3 deal and Acme demo), lease and dinner marked fine.
3. Correction: "Lena is now approved as backup release approver."
4. Run the same question again. The product chain gets shorter.

## Docker
    docker build -t blast-radius .
    docker run -it --env-file .env blast-radius
