import os
import json
import shutil
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import tools
from agent import run_once, run_correct, run_draft_emails

app = FastAPI()

TRIGGER_PATH = os.path.join("reports", "last_trigger.txt")
META_PATH = os.path.join("reports", "run_meta.json")

run_state = {
    "done": True,
    "error": None,
    "last_trigger": "",
    "run_number": 0,
    "updated_at": None,
    "report_saved": False,
    "had_previous": False,
}


class RunRequest(BaseModel):
    message: str


class CorrectRequest(BaseModel):
    fact: str


def clear_outbox():
    outbox_dir = "outbox"
    if not os.path.exists(outbox_dir):
        os.makedirs(outbox_dir)
        return
    names = os.listdir(outbox_dir)
    for name in names:
        path = os.path.join(outbox_dir, name)
        if os.path.isfile(path):
            os.remove(path)


def copy_previous_graph():
    graph_path = os.path.join("reports", "graph.json")
    previous_path = os.path.join("reports", "previous.json")
    if os.path.exists(graph_path):
        shutil.copy(graph_path, previous_path)
        return True
    return False


def read_json_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        text = f.read()
    if text.strip() == "":
        return None
    return json.loads(text)


def load_persisted_state():
    if os.path.exists(TRIGGER_PATH):
        with open(TRIGGER_PATH, "r") as f:
            run_state["last_trigger"] = f.read().strip()
    if os.path.exists(META_PATH):
        meta = read_json_file(META_PATH)
        if meta:
            run_state["run_number"] = meta.get("run_number", 0)
            run_state["updated_at"] = meta.get("updated_at")


def save_persisted_state():
    os.makedirs("reports", exist_ok=True)
    with open(TRIGGER_PATH, "w") as f:
        f.write(run_state["last_trigger"])
    meta = {
        "run_number": run_state["run_number"],
        "updated_at": run_state["updated_at"],
        "last_trigger": run_state["last_trigger"],
    }
    with open(META_PATH, "w") as f:
        f.write(json.dumps(meta))


def read_emails():
    emails = []
    outbox_dir = "outbox"
    if not os.path.exists(outbox_dir):
        return emails
    names = sorted(os.listdir(outbox_dir))
    for name in names:
        path = os.path.join(outbox_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, "r") as f:
            content = f.read()
        to_addr = ""
        subject = ""
        body_lines = []
        lines = content.split("\n")
        body_started = False
        for line in lines:
            if not body_started and line.startswith("To: "):
                to_addr = line[4:]
            elif not body_started and line.startswith("Subject: "):
                subject = line[9:]
            elif not body_started and line.strip() == "":
                body_started = True
            elif body_started:
                body_lines.append(line)
        body = "\n".join(body_lines)
        emails.append({
            "file": name,
            "to": to_addr,
            "subject": subject,
            "body": body,
        })
    return emails


def public_state():
    return {
        "events": list(tools.EVENTS),
        "done": run_state["done"],
        "error": run_state["error"],
        "last_trigger": run_state["last_trigger"],
        "run_number": run_state["run_number"],
        "updated_at": run_state["updated_at"],
        "report_saved": run_state["report_saved"],
        "had_previous": run_state["had_previous"],
    }


def outbox_has_emails():
    outbox_dir = "outbox"
    if not os.path.exists(outbox_dir):
        return False
    names = os.listdir(outbox_dir)
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(outbox_dir, name)
        if os.path.isfile(path):
            return True
    return False


def significant_words(text):
    skip = {
        "with", "from", "that", "this", "have", "been", "will", "into",
        "number", "status", "after", "before", "about", "your", "their",
        "the", "and", "for", "are", "was", "were",
    }
    cleaned = ""
    for ch in str(text or "").lower():
        if ch.isalnum():
            cleaned = cleaned + ch
        else:
            cleaned = cleaned + " "
    words = cleaned.split()
    result = []
    for word in words:
        if len(word) < 4:
            continue
        if word in skip:
            continue
        result.append(word)
    return result


def nodes_changed_to_fine(previous, current):
    changed = []
    if not previous or not current:
        return changed
    prev_map = {}
    for node in previous.get("nodes") or []:
        prev_map[node.get("id")] = node
    for node in current.get("nodes") or []:
        node_id = node.get("id")
        prev = prev_map.get(node_id)
        if not prev:
            continue
        before = prev.get("status", "")
        after = node.get("status", "")
        if before == "at_risk" or before == "at-risk":
            before = "risk"
        if after == "at_risk" or after == "at-risk":
            after = "risk"
        if after == "fine":
            if before == "broken" or before == "risk":
                changed.append(node)
    return changed


def annotate_emails(emails, previous, graph):
    fine_nodes = nodes_changed_to_fine(previous, graph)
    for email in emails:
        email["no_longer_needed"] = False
        blob = (email.get("to", "") + " " + email.get("subject", "") + " " + email.get("body", "")).lower()
        for node in fine_nodes:
            words = significant_words(node.get("label", ""))
            hit = False
            for word in words:
                if word in blob:
                    hit = True
            if hit:
                email["no_longer_needed"] = True
    return emails


async def run_agent_job(message):
    run_state["done"] = False
    run_state["error"] = None
    run_state["report_saved"] = False
    try:
        await run_once(message)
    except Exception as e:
        run_state["error"] = str(e)
        tools.add_event("Error: " + str(e))
    run_state["report_saved"] = tools.REPORT_SAVED
    if tools.REPORT_SAVED:
        if not outbox_has_emails():
            graph = read_json_file(os.path.join("reports", "graph.json"))
            tools.add_event("Drafting emails")
            draft_message = (
                "Here is the blast radius graph: " + json.dumps(graph) + ". "
                "Draft one short, polite email for each of the 2 or 3 most important BROKEN items, "
                "to the person affected (use the email addresses from the sources). "
                "Prefer these addresses when they match: "
                "dana@northwind.example for Northwind/Dana, "
                "jordan@lumenlabs.example for Jordan/board/Q3, "
                "raj@lumenlabs.example for Raj/PR review, "
                "priya@acme.example for Acme/Priya. "
                "Explain the delay and propose a new time. Call draft_email once per email."
            )
            try:
                await run_draft_emails(draft_message)
            except Exception as e:
                tools.add_event("Email draft error: " + str(e))
        run_state["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_persisted_state()
    run_state["done"] = True


async def run_correct_job(message):
    run_state["done"] = False
    run_state["error"] = None
    run_state["report_saved"] = False
    try:
        await run_correct(message)
    except Exception as e:
        run_state["error"] = str(e)
        tools.add_event("Error: " + str(e))
    run_state["report_saved"] = tools.GRAPH_PATCHED
    if tools.GRAPH_PATCHED:
        run_state["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_persisted_state()
    run_state["done"] = True


@app.on_event("startup")
async def on_startup():
    load_persisted_state()


@app.post("/run")
async def start_run(req: RunRequest):
    if not run_state["done"]:
        return {"ok": False, "error": "A run is already in progress"}

    tools.clear_run_flags()
    had_previous = copy_previous_graph()
    clear_outbox()

    message = req.message
    run_state["last_trigger"] = message
    save_persisted_state()

    run_state["run_number"] = run_state["run_number"] + 1
    run_state["had_previous"] = had_previous
    run_state["report_saved"] = False
    run_state["error"] = None
    save_persisted_state()

    tools.add_event("Starting investigation")
    asyncio.create_task(run_agent_job(message))
    return {
        "ok": True,
        "run_number": run_state["run_number"],
        "last_trigger": run_state["last_trigger"],
    }


@app.post("/correct")
async def start_correct(req: CorrectRequest):
    if not run_state["done"]:
        return {"ok": False, "error": "A run is already in progress"}

    graph_path = os.path.join("reports", "graph.json")
    graph = read_json_file(graph_path)
    if graph is None:
        return {"ok": False, "error": "No graph yet. Run a trigger first."}

    tools.clear_run_flags()
    copy_previous_graph()
    # Do not clear outbox. Do not change last_trigger.

    fact = req.fact
    message = (
        "New fact from the user: " + fact + "\n"
        "Step 1: call save_correction with this fact.\n"
        "Step 2: here is the current graph: " + json.dumps(graph) + "\n"
        "Use recall_memory if needed, then decide which EXISTING node ids change status.\n"
        "Step 3: call update_nodes with ONLY those nodes.\n"
        "Rules:\n"
        "- Personal facts about Sam, dinner, or lease almost never change status. Use [].\n"
        "- If Lena is a backup release approver, update product-chain ids that are blocked "
        "without Maya (often pr, qa, gonogo, acme) to status fine with a short reason.\n"
        "- Do not change money-chain ids (northwind, signing, pricing, board) for a Lena fact.\n"
        "If nothing changes, call update_nodes with an empty list [].\n"
        "Do not call save_report. Do not add or remove nodes."
    )

    run_state["run_number"] = run_state["run_number"] + 1
    run_state["had_previous"] = True
    run_state["report_saved"] = False
    run_state["error"] = None
    save_persisted_state()

    tools.add_event("Applying correction")
    asyncio.create_task(run_correct_job(message))
    return {
        "ok": True,
        "run_number": run_state["run_number"],
        "last_trigger": run_state["last_trigger"],
    }


@app.get("/events")
async def get_events():
    return public_state()


@app.get("/result")
async def get_result():
    graph = read_json_file(os.path.join("reports", "graph.json"))
    previous = read_json_file(os.path.join("reports", "previous.json"))
    summary = ""
    summary_path = os.path.join("reports", "summary.txt")
    if os.path.exists(summary_path):
        with open(summary_path, "r") as f:
            summary = f.read()
    emails = read_emails()
    emails = annotate_emails(emails, previous, graph)
    state = public_state()
    state["graph"] = graph
    state["previous"] = previous
    state["summary"] = summary
    state["emails"] = emails
    return state


def clear_reports():
    reports_dir = "reports"
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
        return
    names = [
        "graph.json",
        "previous.json",
        "summary.txt",
        "chain.mmd",
        "blast_radius.html",
        "last_trigger.txt",
        "run_meta.json",
    ]
    for name in names:
        path = os.path.join(reports_dir, name)
        if os.path.isfile(path):
            os.remove(path)


@app.post("/reset")
async def reset_demo():
    if not run_state["done"]:
        return {"ok": False, "error": "Wait for the current run to finish"}

    tools.clear_run_flags()
    clear_outbox()
    clear_reports()
    run_state["error"] = None
    run_state["last_trigger"] = ""
    run_state["run_number"] = 0
    run_state["updated_at"] = None
    run_state["report_saved"] = False
    run_state["had_previous"] = False

    import memory
    await memory.connect()
    await memory.remember(
        "User correction: Demo reset. Ignore earlier user corrections from this session. "
        "Maya Chen remains the sole release approver. Lena is not a backup release approver."
    )
    tools.add_event("Demo reset complete")

    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse("static/index.html")


if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
