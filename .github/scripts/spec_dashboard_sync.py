#!/usr/bin/env python3
import re
import sys
from pathlib import Path


# ── Lifecycle stages ──
# Each feature progresses:  Spec → Checklist → Clarified → Plan → Tasks → Done
# Each user story progresses: Not Started → Planned → In Progress → Done

STAGE_SPEC = "Spec"
STAGE_CHECKLIST = "Checklist"
STAGE_CLARIFIED = "Clarified"
STAGE_PLAN = "Planned"
STAGE_TASKS = "In Progress"
STAGE_DONE = "Complete"


def parse_constitution(constitution_path):
    """Extract principles and version info from the constitution."""
    path = Path(constitution_path)
    if not path.exists():
        return None

    text = path.read_text()

    # Version line
    version = ""
    m = re.search(r"\*\*Version\*\*:\s*(\S+)", text)
    if m:
        version = m.group(1)

    last_amended = ""
    m = re.search(r"\*\*Last Amended\*\*:\s*(\S+)", text)
    if m:
        last_amended = m.group(1)

    # Principles: lines like "### I. SwiftUI-First" or "### VII. Guiding..."
    principles = []
    for m in re.finditer(r"^### ([IVXLC]+)\.\s+(.+)", text, re.MULTILINE):
        principles.append((m.group(1), m.group(2).strip()))

    return {
        "version": version,
        "last_amended": last_amended,
        "principles": principles,
    }


def parse_tasks_file(text):
    """Parse tasks.md to get per-story task counts (done/total) and phase info."""
    story_tasks = {}  # { "US1": {"done": 0, "total": 0} }
    infra_tasks = {"done": 0, "total": 0}  # tasks not tagged with a story

    for m in re.finditer(r"- \[([ x])\]\s+(T\d+)(.+)", text):
        checked = m.group(1) == "x"
        rest = m.group(3)
        us_match = re.search(r"\[(US\d+)\]", rest)
        if us_match:
            us = us_match.group(1)
            story_tasks.setdefault(us, {"done": 0, "total": 0})
            story_tasks[us]["total"] += 1
            if checked:
                story_tasks[us]["done"] += 1
        else:
            infra_tasks["total"] += 1
            if checked:
                infra_tasks["done"] += 1

    # Phase info with per-phase task counts
    phases = []
    phase_sections = re.split(r"(?=## Phase \d+:)", text)
    for section in phase_sections:
        header = re.match(r"## Phase (\d+): (.+)", section)
        if not header:
            continue
        phase_num = header.group(1)
        # Strip emoji and extra whitespace from phase name
        phase_name = re.sub(r"\s*🎯.*", "", header.group(2)).strip()
        done = len(re.findall(r"- \[x\]\s+T\d+", section))
        total = len(re.findall(r"- \[[ x]\]\s+T\d+", section))
        phases.append({
            "num": phase_num,
            "name": phase_name,
            "done": done,
            "total": total,
        })

    return story_tasks, infra_tasks, phases


def parse_feature(feature_dir):
    """Extract full lifecycle info from a feature directory."""
    info = {
        "name": feature_dir.name,
        "title": "",
        "status": "",
        "description": "",
        "stories": [],
        "functional_reqs": 0,
        "success_criteria": [],
        "edge_cases": 0,
        "dependencies": [],
        "assumptions": 0,
        "checklist_pass": 0,
        "checklist_total": 0,
        "has_spec": False,
        "has_checklist": False,
        "has_clarifications": False,
        "clarification_count": 0,
        "has_plan": False,
        "has_tasks": False,
        "story_tasks": {},
        "infra_tasks": {"done": 0, "total": 0},
        "phases": [],
    }

    # ── Spec ──
    spec_file = feature_dir / "spec.md"
    if spec_file.exists():
        info["has_spec"] = True
        text = spec_file.read_text()

        m = re.search(r"^# Feature Specification:\s*(.+)", text, re.MULTILINE)
        if m:
            info["title"] = m.group(1).strip()

        m = re.search(r"\*\*Status\*\*:\s*(.+)", text)
        if m:
            info["status"] = m.group(1).strip()

        m = re.search(r'\*\*Input\*\*:\s*User description:\s*"(.+?)"', text)
        if m:
            info["description"] = m.group(1).strip()

        for m in re.finditer(
            r"### User Story (\d+) - (.+?) \(Priority: (P[1-3])\)", text
        ):
            info["stories"].append(
                {"num": m.group(1), "title": m.group(2), "priority": m.group(3)}
            )

        info["functional_reqs"] = len(re.findall(r"\*\*FR-\d+\*\*:", text))

        for m in re.finditer(r"\*\*(SC-\d+)\*\*:\s*(.+)", text):
            info["success_criteria"].append((m.group(1), m.group(2).strip()))

        edge_section = re.search(
            r"### Edge Cases\s*\n(.*?)(?=\n##|\n---|\Z)", text, re.DOTALL
        )
        if edge_section:
            info["edge_cases"] = len(
                re.findall(r"^- ", edge_section.group(1), re.MULTILINE)
            )

        dep_section = re.search(
            r"## Dependencies\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL
        )
        if dep_section:
            for m in re.finditer(r"\*\*(.+?)\*\*:\s*(.+)", dep_section.group(1)):
                info["dependencies"].append((m.group(1), m.group(2).strip()))

        assume_section = re.search(
            r"## Assumptions\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL
        )
        if assume_section:
            info["assumptions"] = len(
                re.findall(r"^- ", assume_section.group(1), re.MULTILINE)
            )

        # Clarifications
        clarify_section = re.search(
            r"## Clarifications\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL
        )
        if clarify_section:
            count = len(re.findall(r"^- Q:", clarify_section.group(1), re.MULTILINE))
            if count > 0:
                info["has_clarifications"] = True
                info["clarification_count"] = count

    # ── Checklist ──
    checklist_file = feature_dir / "checklists" / "requirements.md"
    if checklist_file.exists():
        info["has_checklist"] = True
        text = checklist_file.read_text()
        info["checklist_pass"] = len(re.findall(r"- \[x\]", text))
        info["checklist_total"] = len(re.findall(r"- \[.\]", text))

    # ── Plan ──
    plan_artifacts = ["research.md", "data-model.md", "quickstart.md"]
    info["plan_present"] = sum(
        1 for a in plan_artifacts if (feature_dir / a).exists()
    )
    # contracts/ counts if directory exists and has at least one file
    contracts_dir = feature_dir / "contracts"
    if contracts_dir.is_dir() and any(contracts_dir.iterdir()):
        info["plan_present"] += 1
    info["plan_total"] = len(plan_artifacts) + 1  # +1 for contracts/
    info["has_plan"] = info["plan_present"] > 0

    # ── Tasks ──
    tasks_file = feature_dir / "tasks.md"
    if tasks_file.exists():
        info["has_tasks"] = True
        text = tasks_file.read_text()
        info["story_tasks"], info["infra_tasks"], info["phases"] = parse_tasks_file(
            text
        )

    return info


def feature_stage(info):
    """Determine overall feature lifecycle stage."""
    if info["has_tasks"]:
        st = info["story_tasks"]
        infra = info["infra_tasks"]
        total = sum(s["total"] for s in st.values()) + infra["total"]
        done = sum(s["done"] for s in st.values()) + infra["done"]
        if total > 0 and done == total:
            return STAGE_DONE
        return STAGE_TASKS
    if info["has_plan"]:
        return STAGE_PLAN
    if info["has_clarifications"]:
        return STAGE_CLARIFIED
    if info["has_checklist"] and info["checklist_pass"] == info["checklist_total"]:
        return STAGE_CHECKLIST
    if info["has_spec"]:
        return STAGE_SPEC
    return "—"


def story_status(info, story_num):
    """Determine a single user story's implementation status."""
    us_key = f"US{story_num}"
    if not info["has_tasks"]:
        return "—"
    st = info["story_tasks"].get(us_key)
    if not st:
        return "No Tasks"
    if st["done"] == st["total"]:
        return "Done"
    if st["done"] > 0:
        return "In Progress"
    return "Not Started"


def progress_bar(done, total):
    """Render a small text progress indicator."""
    if total == 0:
        return "—"
    pct = int(done / total * 100)
    filled = round(done / total * 5)
    bar = "█" * filled + "░" * (5 - filled)
    return f"{bar} {done}/{total} ({pct}%)"


def priority_badge(p):
    return p


_LOREM = [
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
    "elit", "sed", "eiusmod", "tempor", "incididunt", "labore", "dolore",
    "magna", "aliqua", "enim", "minim", "veniam", "nostrud", "exercitation",
    "ullamco", "laboris", "aliquip", "commodo", "consequat", "aute", "irure",
    "reprehenderit", "voluptate", "velit", "esse", "cillum", "fugiat",
    "nulla", "pariatur", "excepteur", "sint", "occaecat", "cupidatat",
    "proident", "culpa", "officia", "deserunt", "mollit", "laborum",
    "porta", "nibh", "venenatis", "pulvinar", "mattis", "blandit", "vitae",
    "congue", "mauris", "rhoncus", "aenean", "lacus", "viverra", "maecenas",
    "accumsan", "pharetra", "pellentesque", "habitant", "morbi", "tristique",
    "senectus", "malesuada", "fames", "turpis", "egestas", "praesent",
    "elementum", "facilisis", "sapien", "faucibus", "scelerisque", "feugiat",
    "pretium", "lectus", "volutpat", "consequat", "semper", "auctor",
    "neque", "ornare", "tortor", "condimentum", "interdum", "posuere",
]


def _greek_phrase(text, counter):
    """Replace each word in a phrase with a lorem ipsum word, preserving caps."""
    words = text.split()
    out = []
    for w in words:
        lw = _LOREM[counter[0] % len(_LOREM)]
        if w[0:1].isupper():
            lw = lw.capitalize()
        out.append(lw)
        counter[0] += 1
    return " ".join(out)


def _greek_slug(name, counter):
    """Greek a feature directory name like '001-streaming-watch-history' → '001-lorem-ipsum'."""
    parts = name.split("-", 1)  # ['001', 'streaming-watch-history']
    if len(parts) < 2:
        return name
    num = parts[0]
    words = parts[1].split("-")
    greek_words = []
    for w in words:
        greek_words.append(_LOREM[counter[0] % len(_LOREM)])
        counter[0] += 1
    return f"{num}-{'-'.join(greek_words)}"


def _greek_features(features, counter):
    """Replace user-authored strings in parsed feature data with lorem ipsum."""
    for f in features:
        f["name"] = _greek_slug(f["name"], counter)
        if f["title"]:
            f["title"] = _greek_phrase(f["title"], counter)
        if f["description"]:
            f["description"] = _greek_phrase(f["description"], counter)
        f["stories"] = [
            {**s, "title": _greek_phrase(s["title"], counter)}
            for s in f["stories"]
        ]
        f["success_criteria"] = [
            (sc_id, _greek_phrase(desc, counter))
            for sc_id, desc in f["success_criteria"]
        ]
        f["dependencies"] = [
            (_greek_phrase(label, counter), _greek_phrase(desc, counter))
            for label, desc in f["dependencies"]
        ]
        f["phases"] = [
            {**p, "name": _greek_phrase(p["name"], counter)}
            for p in f["phases"]
        ]


def _greek_constitution(constitution, counter):
    """Replace principle names with lorem ipsum."""
    if not constitution:
        return
    constitution["principles"] = [
        (numeral, _greek_phrase(name, counter))
        for numeral, name in constitution["principles"]
    ]


def generate_dashboard(specs_dir, greek=False):
    specs_path = Path(specs_dir)
    if not specs_path.exists():
        print(f"Specs directory not found: {specs_dir}", file=sys.stderr)
        sys.exit(1)

    features = []
    for d in sorted(specs_path.iterdir()):
        if d.is_dir():
            features.append(parse_feature(d))

    # ── Greek mode: replace user-authored content with lorem ipsum ──
    counter = [0]  # mutable counter shared across calls
    constitution = parse_constitution(".specify/memory/constitution.md")
    if greek:
        _greek_features(features, counter)
        _greek_constitution(constitution, counter)

    out = []
    out.append("# Spec Dashboard")
    out.append("")
    out.append("> Auto-generated from `specs/` — do not edit manually.")
    out.append("")

    # ── Constitution summary ──
    if constitution:
        out.append("## Constitution")
        out.append("")
        version_parts = [f"v{constitution['version']}"]
        if constitution["last_amended"]:
            version_parts.append(f"amended {constitution['last_amended']}")
        out.append(
            f"*{' · '.join(version_parts)}* · "
            f"[Full document](.specify/memory/constitution.md)"
        )
        out.append("")
        out.append("| # | Principle |")
        out.append("|---|-----------|")
        for numeral, name in constitution["principles"]:
            # Build GitHub-compatible anchor from heading text
            anchor_text = f"{numeral}. {name}".lower()
            anchor = re.sub(r"[^\w\s-]", "", anchor_text).replace(" ", "-")
            link = f".specify/memory/constitution.md#{anchor}"
            out.append(f"| {numeral} | [{name}]({link}) |")
        out.append("")

    # ── Feature overview table ──
    out.append("## Feature Overview")
    out.append("")
    out.append("| # | Feature | Stage | Checklist | Clarify | Plan | Tasks |")
    out.append("|---|---------|-------|-----------|---------|------|-------|")
    for f in features:
        num = f["name"].split("-")[0]
        title = f["title"] or f["name"]
        stage = feature_stage(f)

        if f["has_checklist"]:
            cl_col = (
                f"✅ {f['checklist_pass']}/{f['checklist_total']}"
                if f["checklist_pass"] == f["checklist_total"]
                else f"⚠️ {f['checklist_pass']}/{f['checklist_total']}"
            )
        else:
            cl_col = "—"
        clarify_col = "✅" if f["has_clarifications"] else "—"
        if f["has_plan"]:
            plan_col = (
                f"✅ {f['plan_present']}/{f['plan_total']}"
                if f["plan_present"] == f["plan_total"]
                else f"⚠️ {f['plan_present']}/{f['plan_total']}"
            )
        else:
            plan_col = "—"

        if f["has_tasks"]:
            st = f["story_tasks"]
            infra = f["infra_tasks"]
            total = sum(s["total"] for s in st.values()) + infra["total"]
            done = sum(s["done"] for s in st.values()) + infra["done"]
            tasks_col = f"{done}/{total}"
        else:
            tasks_col = "—"

        out.append(
            f"| {num} | [{title}](specs/{f['name']}/spec.md) | **{stage}** | {cl_col} | {clarify_col} | {plan_col} | {tasks_col} |"
        )

    # ── Per-feature detail sections ──
    for f in features:
        title = f["title"] or f["name"]
        stage = feature_stage(f)

        out.append("")
        out.append("---")
        out.append("")
        out.append(f"## {title}")
        out.append("")
        if f["description"]:
            out.append(f"> {f['description']}")
            out.append("")

        # Lifecycle progress
        stages = [STAGE_SPEC, STAGE_CHECKLIST, STAGE_CLARIFIED, STAGE_PLAN, STAGE_TASKS, STAGE_DONE]
        current_idx = stages.index(stage) if stage in stages else -1
        markers = []
        for i, s in enumerate(stages):
            if i < current_idx:
                markers.append(f"~~{s}~~")
            elif i == current_idx:
                markers.append(f"**{s}**")
            else:
                markers.append(s)
        out.append(f"📍 {' → '.join(markers)}")
        out.append("")

        # User story table with status
        if f["stories"]:
            out.append("### User Stories")
            out.append("")
            out.append("| # | Story | Priority | Status | Progress |")
            out.append("|---|-------|----------|--------|----------|")
            for s in f["stories"]:
                status = story_status(f, s["num"])
                us_key = f"US{s['num']}"
                if f["has_tasks"] and us_key in f["story_tasks"]:
                    t = f["story_tasks"][us_key]
                    prog = progress_bar(t["done"], t["total"])
                else:
                    prog = "—"
                # Link story title to its heading in the spec
                heading = f"User Story {s['num']} - {s['title']} Priority {s['priority']}"
                anchor = re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
                spec_link = f"specs/{f['name']}/spec.md#{anchor}"
                out.append(
                    f"| {s['num']} | [{s['title']}]({spec_link}) | {s['priority']} | {status} | {prog} |"
                )

            out.append("")

        # Task phases
        if f["has_tasks"] and f["phases"]:
            out.append("### Tasks")
            out.append("")
            out.append("| Phase | Name | Progress |")
            out.append("|-------|------|----------|")
            for p in f["phases"]:
                prog = progress_bar(p["done"], p["total"])
                anchor = re.sub(r"[^\w\s-]", "", f"phase {p['num']} {p['name']}".lower()).replace(" ", "-")
                tasks_link = f"specs/{f['name']}/tasks.md#{anchor}"
                out.append(f"| {p['num']} | [{p['name']}]({tasks_link}) | {prog} |")
            out.append("")

        # Success criteria
        if f["success_criteria"]:
            out.append("### Success Criteria")
            out.append("")
            for sc_id, desc in f["success_criteria"]:
                out.append(f"- **{sc_id}**: {desc}")
            out.append("")

        # Dependencies
        if f["dependencies"]:
            out.append("### Dependencies")
            out.append("")
            for label, desc in f["dependencies"]:
                out.append(f"- *{label}*: {desc}")
            out.append("")

        # Compact stats footer
        stats = []
        stats.append(f"{f['functional_reqs']} reqs")
        stats.append(f"{f['edge_cases']} edge cases")
        stats.append(f"{f['assumptions']} assumptions")
        out.append(f"*{' · '.join(stats)}*")
        out.append("")

    return "\n".join(out)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate spec dashboard")
    parser.add_argument("input_file", nargs="?", help="Read and print a file")
    parser.add_argument(
        "--output",
        default="SPEC-DASHBOARD.md",
        help="Output filename (default: SPEC-DASHBOARD.md)",
    )
    parser.add_argument(
        "--greek",
        action="store_true",
        help="Replace English text with lorem ipsum placeholder text",
    )
    args = parser.parse_args()

    if args.input_file:
        text = Path(args.input_file).read_text()
        print(text)
    else:
        dashboard = generate_dashboard("specs", greek=args.greek)
        Path(args.output).write_text(dashboard + "\n")
        print(f"Generated {args.output}")
