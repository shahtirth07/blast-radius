import os
import json
import shutil
import asyncio
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import tools
from agent import run_once

app = FastAPI()

run_state = {
    "done": True,
    "error": None,
}


class RunRequest(BaseModel):
    message: str


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


def read_json_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        text = f.read()
    if text.strip() == "":
        return None
    return json.loads(text)


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


async def run_agent_job(message):
    run_state["done"] = False
    run_state["error"] = None
    try:
        await run_once(message)
    except Exception as e:
        run_state["error"] = str(e)
        tools.add_event("Error: " + str(e))
    run_state["done"] = True


@app.post("/run")
async def start_run(req: RunRequest):
    if not run_state["done"]:
        return {"ok": False, "error": "A run is already in progress"}

    tools.EVENTS.clear()
    copy_previous_graph()
    clear_outbox()
    tools.add_event("Starting investigation")

    asyncio.create_task(run_agent_job(req.message))
    return {"ok": True}


@app.get("/events")
async def get_events():
    return {
        "events": list(tools.EVENTS),
        "done": run_state["done"],
        "error": run_state["error"],
    }


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
    return {
        "graph": graph,
        "previous": previous,
        "summary": summary,
        "emails": emails,
        "done": run_state["done"],
        "error": run_state["error"],
    }


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
    ]
    for name in names:
        path = os.path.join(reports_dir, name)
        if os.path.isfile(path):
            os.remove(path)


@app.post("/reset")
async def reset_demo():
    if not run_state["done"]:
        return {"ok": False, "error": "Wait for the current run to finish"}

    tools.EVENTS.clear()
    clear_outbox()
    clear_reports()
    run_state["error"] = None

    # Undo teach-it corrections so the Lena demo can be shown again
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
