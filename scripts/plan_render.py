"""The plan's status, rendered for a person to read: otsafety-gnn's report format.

PURE: a plan and a validated status in, text out. It decides nothing -- the
policy did -- so it needs no policy of its own.

GROUPED BY THREAD. The source groups by phase; this repository has no phases,
and its threads are its capability groups. One mark is added for the state this
port introduced: unknown, when the only gap is evidence that could not be seen.
"""

from __future__ import annotations

from plan_models import PlanStatus, ProjectPlan

MARK = {"done": "✅", "in_progress": "🔵", "ready": "⬜", "blocked": "🔒", "unknown": "❔"}


def render(plan: ProjectPlan, status: PlanStatus) -> str:
    states = {step_id: entry.state for step_id, entry in status.steps.items()}
    done = sum(1 for state in states.values() if state == "done")
    out = [f"PROJECT PLAN -- observed on {status.ref}: {done} of {len(plan.steps)} steps done", ""]

    for thread in plan.threads:
        rows = [step for step in plan.steps if step.thread == thread.id]
        if not rows:
            continue
        finished = sum(1 for step in rows if states[step.id] == "done")
        out.append(f"-- Thread {thread.id} . {thread.title}  ({finished}/{len(rows)})")
        for step in rows:
            entry = status.steps[step.id]
            waits = f"   [after {', '.join(entry.blocked_by)}]" if entry.state == "blocked" else ""
            out.append(f"   {MARK[entry.state]} {step.id:5s} {step.title[:84]}{waits}")
        out.append("")

    out.append("-- THREADS, computed from the steps above")
    for thread in plan.threads:
        rows = [step for step in plan.steps if step.thread == thread.id]
        finished = sum(1 for step in rows if states[step.id] == "done")
        filled = round(20 * finished / len(rows)) if rows else 0
        bar = "#" * filled + "." * (20 - filled)
        out.append(f"   {thread.id} {thread.title[:38]:38s} {bar} {finished:3d}/{len(rows):<3d}")

    titles = {step.id: step.title for step in plan.steps}
    now = [i for i, s in states.items() if s == "in_progress"] + [
        i for i, s in states.items() if s == "ready"
    ]
    out += ["", "-- NOW: in progress, then ready to start"]
    out += [f"   {MARK[states[i]]} {i:5s} {titles[i][:88]}" for i in now]

    out += [
        "",
        f"-- DECISIONS ({len(plan.decisions)}): deliberately not done, each with its reason",
    ]
    out += [f"   {d.state[:10]:10s} {d.id:9s} {d.title[:80]}" for d in plan.decisions]
    return "\n".join(out)
