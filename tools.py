import os
import re
import requests
from datetime import datetime
from strands import tool
import memory


EVENTS = []
REPORT_SAVED = False
GRAPH_PATCHED = False


def add_event(text):
    EVENTS.append(text)


def clear_run_flags():
    global REPORT_SAVED
    global GRAPH_PATCHED
    EVENTS.clear()
    REPORT_SAVED = False
    GRAPH_PATCHED = False


@tool
async def recall_memory(question: str) -> str:
    """Ask the personal brain a question.
    Use it to find what depends on an event, person, or deadline.
    Example: "What depends on the Northwind walkthrough on Thursday?"
    """
    add_event("Recall: " + question)
    return await memory.recall(question)


@tool
async def save_correction(fact: str) -> str:
    """Save a correction or new fact from the user into long-term memory.
    Example: "Lena is now approved as backup release approver."
    """
    add_event("Saving correction: " + fact)
    await memory.remember("User correction: " + fact)
    return "Saved to memory: " + fact


@tool
def check_flight(flight_number: str) -> str:
    """Check the live public status of a flight using Bright Data."""
    add_event("Checking flight " + flight_number)
    demo_status = os.getenv("DEMO_FLIGHT_STATUS")
    if demo_status:
        return "Flight " + flight_number + ": " + demo_status

    api_key = os.getenv("BRIGHTDATA_API_KEY")
    zone = os.getenv("BRIGHTDATA_ZONE")
    search_url = "https://www.google.com/search?q=" + flight_number.replace(" ", "+") + "+flight+status"

    response = requests.post(
        "https://api.brightdata.com/request",
        headers={"Authorization": "Bearer " + api_key},
        json={"zone": zone, "url": search_url, "format": "raw"},
        timeout=60,
    )

    # Strip HTML tags so the agent gets plain text
    text = re.sub(r"<[^>]+>", " ", response.text)
    text = re.sub(r"\s+", " ", text)
    return text[:3000]


@tool
def draft_email(to: str, subject: str, body: str) -> str:
    """Draft a follow-up or reschedule email. Saves it to the outbox folder."""
    add_event("Drafting email to " + to)
    stamp = datetime.now().strftime("%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", to)
    path = os.path.join("outbox", stamp + "_" + safe_name + ".txt")
    with open(path, "w") as f:
        f.write("To: " + to + "\nSubject: " + subject + "\n\n" + body)
    return "Draft saved: " + path


@tool
def save_report(mermaid_graph: str, summary: str, graph_json: str = "") -> str:
    """Save the blast radius report as HTML, Mermaid, and JSON graph.
    mermaid_graph: a Mermaid 'graph TD' diagram. Mark broken nodes with :::broken,
    at-risk nodes with :::risk, and fine nodes with :::fine.
    summary: plain-English summary with the damage score and recommendation.
    graph_json: a JSON string with nodes, edges, score, confidence, recommendation.
    Each node needs id, label, status (broken|risk|fine), source, reason, severity.
    Include every FINE item too.
    """
    global REPORT_SAVED
    add_event("Saving blast radius report")
    REPORT_SAVED = True

    html = """<!doctype html><html><head><meta charset="utf-8">
<title>Blast Radius</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>body{font-family:sans-serif;max-width:900px;margin:40px auto;padding:0 20px}
pre.summary{white-space:pre-wrap;font-family:sans-serif;font-size:16px;line-height:1.6}</style>
</head><body><h1>Blast Radius</h1>
<pre class="mermaid">
%%GRAPH%%
classDef broken fill:#fcebeb,stroke:#a32d2d,color:#501313
classDef risk fill:#faeeda,stroke:#854f0b,color:#412402
classDef fine fill:#eaf3de,stroke:#3b6d11,color:#173404
</pre>
<pre class="summary">%%SUMMARY%%</pre>
<script>mermaid.initialize({startOnLoad:true});</script>
</body></html>"""
    html = html.replace("%%GRAPH%%", mermaid_graph)
    html = html.replace("%%SUMMARY%%", summary)

    os.makedirs("reports", exist_ok=True)

    html_path = os.path.join("reports", "blast_radius.html")
    with open(html_path, "w") as f:
        f.write(html)

    mmd_path = os.path.join("reports", "chain.mmd")
    with open(mmd_path, "w") as f:
        f.write(mermaid_graph)

    summary_path = os.path.join("reports", "summary.txt")
    with open(summary_path, "w") as f:
        f.write(summary)

    if graph_json.strip() != "":
        import json
        try:
            data = json.loads(graph_json)
            nodes = data.get("nodes", [])
            for node in nodes:
                status = node.get("status", "")
                if status == "at_risk" or status == "at-risk" or status == "AT RISK":
                    node["status"] = "risk"
                if status == "BROKEN":
                    node["status"] = "broken"
                if status == "FINE":
                    node["status"] = "fine"
            graph_json = json.dumps(data)
        except Exception:
            pass
        graph_path = os.path.join("reports", "graph.json")
        with open(graph_path, "w") as f:
            f.write(graph_json)

    return "Report saved: " + html_path


def recompute_score(nodes):
    has_high_broken = False
    has_broken_or_risk = False
    i = 0
    while i < len(nodes):
        node = nodes[i]
        status = node.get("status", "")
        if status == "at_risk" or status == "at-risk":
            status = "risk"
        severity = node.get("severity", "")
        if status == "broken" and severity == "high":
            has_high_broken = True
        if status == "broken" or status == "risk":
            has_broken_or_risk = True
        i = i + 1
    if has_high_broken:
        return "HIGH"
    if has_broken_or_risk:
        return "MEDIUM"
    return "LOW"


@tool
def update_nodes(changes_json: str) -> str:
    """Patch existing nodes in reports/graph.json. Does not add or remove nodes.
    changes_json: JSON list like
    [{"id":"raj_pr","status":"fine","reason":"Lena can approve releases now"}]
    Pass [] if nothing changes.
    """
    global GRAPH_PATCHED
    import json

    add_event("Updating graph nodes")
    GRAPH_PATCHED = True

    graph_path = os.path.join("reports", "graph.json")
    if not os.path.exists(graph_path):
        add_event("No graph.json to update")
        return "No graph.json found"

    with open(graph_path, "r") as f:
        raw = f.read()
    if raw.strip() == "":
        add_event("graph.json is empty")
        return "graph.json is empty"

    data = json.loads(raw)
    nodes = data.get("nodes", [])
    if changes_json.strip() == "":
        changes = []
    else:
        changes = json.loads(changes_json)

    if changes is None:
        changes = []

    changed_ids = []
    c = 0
    while c < len(changes):
        change = changes[c]
        target_id = change.get("id", "")
        found = False
        n = 0
        while n < len(nodes):
            node = nodes[n]
            if node.get("id") == target_id:
                found = True
                if "status" in change:
                    status = change.get("status", "")
                    if status == "at_risk" or status == "at-risk" or status == "AT RISK":
                        status = "risk"
                    if status == "BROKEN":
                        status = "broken"
                    if status == "FINE":
                        status = "fine"
                    node["status"] = status
                if "reason" in change:
                    node["reason"] = change.get("reason", "")
                changed_ids.append(target_id)
                add_event("Updated node " + target_id)
            n = n + 1
        if not found:
            add_event("Unknown node id skipped: " + str(target_id))
        c = c + 1

    data["nodes"] = nodes
    data["score"] = recompute_score(nodes)

    with open(graph_path, "w") as f:
        f.write(json.dumps(data))

    if len(changed_ids) == 0:
        return "No nodes changed"
    return "Changed nodes: " + ", ".join(changed_ids)
