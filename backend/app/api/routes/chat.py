from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, delete, or_

from app.core.database import get_session
from app.api.deps import get_current_user
from app.core.config import settings
from app.models import User, Todo, ChatMessage
from app.schemas.chat import ChatIn, ChatOut

import google.generativeai as genai

router = APIRouter(prefix="/chat", tags=["chat"])


# =========================================================
# Local numbering helpers (Todo 1..N per user)
# =========================================================
def _get_user_todos(session: Session, user_id: int) -> List[Todo]:
    return session.exec(
        select(Todo).where(Todo.user_id == user_id).order_by(Todo.id.asc())
    ).all()


def _resolve_local_to_db_id(
    session: Session, user_id: int, local_no: Optional[int]
) -> Optional[int]:
    if not local_no or local_no <= 0:
        return None
    todos = _get_user_todos(session, user_id)
    if local_no > len(todos):
        return None
    return todos[local_no - 1].id


def _resolve_many_local_to_db_ids(
    session: Session, user_id: int, local_nos: List[int]
) -> List[int]:
    todos = _get_user_todos(session, user_id)
    out: List[int] = []
    for n in sorted(set(local_nos)):
        if 1 <= n <= len(todos):
            out.append(todos[n - 1].id)
    return out


def _has_attr(obj: Any, name: str) -> bool:
    return hasattr(obj, name)


def _human_list(nums: List[int]) -> str:
    nums = sorted(set(nums))
    if not nums:
        return ""
    if len(nums) == 1:
        return str(nums[0])
    if len(nums) == 2:
        return f"{nums[0]} and {nums[1]}"
    return ", ".join(map(str, nums[:-1])) + f", and {nums[-1]}"


def format_todos_for_user(session: Session, user_id: int, todos: List[Todo]) -> str:
    if not todos:
        return "No todos found."

    all_todos = _get_user_todos(session, user_id)
    local_map = {t.id: i + 1 for i, t in enumerate(all_todos)}

    lines: List[str] = []
    for t in todos:
        mark = "✅" if getattr(t, "completed", False) else "⏳"
        desc = f" — {t.description}" if getattr(t, "description", None) else ""
        pr = ""
        if _has_attr(t, "priority") and getattr(t, "priority", None) is not None:
            pr = f" [p{getattr(t, 'priority')}]"

        lines.append(f"{mark} Todo {local_map.get(t.id, '?')}{pr}: {t.title}{desc}")

    return "\n".join(lines)


# =========================================================
# Parsing utilities
# =========================================================
def _extract_all_ints(text: str) -> List[int]:
    return [int(x) for x in re.findall(r"\b(\d+)\b", text)]


def _extract_ranges_and_lists(text: str) -> List[int]:
    """
    Supports:
      - "1 to 4", "1-4"
      - "3, 5, and 7"
      - "todo 2"
      - "delete 2"
    """
    t = text.lower()
    out: List[int] = []

    for a, b in re.findall(r"\b(\d+)\s*(?:to|-)\s*(\d+)\b", t):
        start, end = int(a), int(b)
        if start <= end:
            out.extend(list(range(start, end + 1)))
        else:
            out.extend(list(range(end, start + 1)))

    out.extend(_extract_all_ints(t))
    return sorted(set(out))


def _extract_ordinal_refs(text: str) -> Optional[int]:
    """
    Supports:
      - "last", "second last"
      - "2nd", "third"
    Returns local index; negative means from end.
    """
    t = text.lower().strip()

    if "second last" in t or "2nd last" in t or "second-last" in t:
        return -2
    if "last" in t or "latest" in t:
        return -1

    m = re.search(r"\b(\d+)(st|nd|rd|th)\b", t)
    if m:
        return int(m.group(1))

    words = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
    }
    for k, v in words.items():
        if re.search(rf"\b{k}\b", t):
            return v
    return None


def _split_multi_items(text: str) -> List[str]:
    """
    For: "Add 3 todos: buy milk, buy eggs, buy bread"
    """
    if ":" in text:
        after = text.split(":", 1)[1].strip()
        parts = [p.strip(" '\"\n\t") for p in after.split(",") if p.strip()]
        return parts

    m = re.search(r"\badd\s+\d+\s+todos?\b(.+)$", text, flags=re.I)
    if m:
        after = m.group(1)
        parts = [p.strip(" '\"\n\t") for p in after.split(",") if p.strip()]
        return parts

    return []


# =========================================================
# Intent parser (English questions only)
# Returns multi-actions (e.g., "delete todo 2 and show remaining todos")
# =========================================================
Parsed = Tuple[str, Dict[str, Any]]  # (action, payload)


def parse_intent_fast(text: str) -> List[Parsed]:
    raw = re.sub(r"\s+", " ", text.strip())
    t = raw.lower()

    # -------------------------------------------------
    # CHAINING HELPERS (and show/list)
    # -------------------------------------------------
    wants_show_after = False
    if re.search(r"\b(and|then)\s+(show|list)\b", t):
        wants_show_after = True

    # -------------------------
    # Status: "todo 1 is completed/incomplete/done/pending"
    # Also: "I've completed todo 3", "task 2 is done"
    # -------------------------
    m_status = re.search(
        r"\b(?:todo|task)\s+(\d+)\s+is\s+(completed|done|finished|pending|incomplete|not done|undone)\b",
        t,
    )
    if m_status:
        local_no = int(m_status.group(1))
        word = m_status.group(2)
        completed = True
        if word in ["pending", "incomplete", "not done", "undone"]:
            completed = False
        actions: List[Parsed] = [("complete_many", {"local_nos": [local_no], "completed": completed})]
        if wants_show_after:
            actions.append(("list", {"filter": "all", "priority": None, "sort_by": None, "sort_dir": None, "limit": None}))
        return actions

    m_status2 = re.search(
        r"\b(i[' ]?ve|i have|i)\s+(completed|done with|finished)\s+(?:todo|task)\s+(\d+)\b",
        t,
    )
    if m_status2:
        local_no = int(m_status2.group(3))
        actions: List[Parsed] = [("complete_many", {"local_nos": [local_no], "completed": True})]
        if wants_show_after:
            actions.append(("list", {"filter": "all", "priority": None, "sort_by": None, "sort_dir": None, "limit": None}))
        return actions

    # -------------------------
    # Latest/last todo quick detail
    # -------------------------
    if "latest todo" in t or "my latest todo" in t or "last todo" in t or "my last todo" in t:
        return [("details", {"ordinal": -1})]

    # -------------------------
    # Show todo number 3 / show todo 3
    # -------------------------
    m_show_one = re.search(r"\bshow\s+(?:todo|task)\s+(?:number\s+)?(\d+)\b", t)
    if m_show_one:
        return [("details", {"local_nos": [int(m_show_one.group(1))]})]

    # -------------------------
    # Show first 5 todos
    # -------------------------
    m_first_n = re.search(r"\bshow\s+first\s+(\d+)\s+(?:todos|tasks)\b", t)
    if m_first_n:
        n = max(1, int(m_first_n.group(1)))
        return [("list", {"filter": "all", "priority": None, "sort_by": "created", "sort_dir": "asc", "limit": n})]

    # -------------------------
    # Which todo has title/description?
    # -------------------------
    if any(k in t for k in ["which todo", "which task"]):
        m = re.search(
            r"(?:title)\s*(?:is|=|:)?\s*['\"]?(.+?)['\"]?\??$",
            raw,
            flags=re.I,
        )
        if not m:
            m = re.search(
                r"(?:desc|description|details)\s*(?:is|=|:)?\s*['\"]?(.+?)['\"]?\??$",
                raw,
                flags=re.I,
            )
        if m:
            q = m.group(1).strip()
            return [("search", {"query": q})]

        m2 = re.search(
            r"(?:which\s+(?:todo|task))\s+(?:has|contains|include|mentions)\s+['\"]?(.+?)['\"]?\??$",
            raw,
            flags=re.I,
        )
        if m2:
            q = m2.group(1).strip()
            return [("search", {"query": q})]

        return [("clarify", {"message": "What title/description should I look for?"})]

    # -------------------------
    # Search / Find
    # -------------------------
    if t.startswith(("find", "search")) or "do i have any todo" in t:
        m = re.search(
            r"(?:find|search)\s+(?:todos?|tasks?)\s*(?:related to|with word|containing|that contain)?\s*['\"]?(.+?)['\"]?$",
            raw,
            flags=re.I,
        )
        q = (m.group(1).strip() if m else "").strip()
        if not q:
            m2 = re.search(
                r"do i have any todos?\s+(?:for|about)\s+(.+)\??$", raw, flags=re.I
            )
            q = m2.group(1).strip() if m2 else ""
        return [("search", {"query": q})]

    # -------------------------
    # Delete all / clear
    # -------------------------
    if any(
        k in t
        for k in [
            "delete all",
            "clear my todo",
            "clear my list",
            "remove everything",
            "delete everything",
        ]
    ):
        return [("delete_all", {})]

    # -------------------------
    # Delete filtered
    # -------------------------
    if "delete all completed" in t or "delete completed" in t:
        return [("delete_filtered", {"filter": "completed"})]
    if "delete all pending" in t or "delete pending" in t:
        return [("delete_filtered", {"filter": "pending"})]

    # -------------------------
    # Count / Summary
    # -------------------------
    if any(k in t for k in ["how many", "count", "total"]) and any(
        k in t for k in ["todo", "todos", "task", "tasks"]
    ):
        if "completed" in t or "done" in t:
            return [("count", {"filter": "completed"})]
        if "pending" in t or "incomplete" in t:
            return [("count", {"filter": "pending"})]
        return [("count", {"filter": "all"})]

    if "summary" in t and any(k in t for k in ["todo", "todos", "task", "tasks"]):
        return [("summary", {})]

    # -------------------------
    # Details (extra)
    # -------------------------
    if t.startswith(("show details", "details of", "what is todo", "what is task")) or (
        "which todo is number" in t
    ):
        nums = _extract_ranges_and_lists(t)
        if nums:
            return [("details", {"local_nos": nums})]
        ordref = _extract_ordinal_refs(t)
        if ordref:
            return [("details", {"ordinal": ordref})]
        return [("clarify", {"message": "Which todo number do you want details for?"})]

    # -------------------------
    # List / View with filters
    # (Added: "anything pending", "what's on my list", "do i have any tasks")
    # -------------------------
    if any(
        k in t
        for k in [
            "show",
            "list",
            "what do i have to do",
            "my todo list",
            "my todos",
            "todo list",
            "do i have any tasks",
            "what’s on my list",
            "what's on my list",
            "anything pending",
            "anything left",
        ]
    ) and not t.startswith(
        (
            "add",
            "create",
            "make",
            "delete",
            "remove",
            "update",
            "patch",
            "edit",
            "change",
            "mark",
            "toggle",
            "complete",
            "uncomplete",
            "reopen",
            "rename",
        )
    ):
        flt = "all"
        if "completed" in t or "done" in t:
            flt = "completed"
        elif "pending" in t or "incomplete" in t:
            flt = "pending"

        priority = None
        if "high priority" in t or "highest priority" in t:
            priority = "high"

        sort_by = None
        sort_dir = None
        if "sort" in t:
            sort_by = "created"
            if "status" in t:
                sort_by = "status"
            if "priority" in t:
                sort_by = "priority"
            sort_dir = "desc" if ("descending" in t or "desc" in t) else "asc"

        return [
            (
                "list",
                {
                    "filter": flt,
                    "priority": priority,
                    "sort_by": sort_by,
                    "sort_dir": sort_dir,
                    "limit": None,
                },
            )
        ]

    # -------------------------
    # Add / Create (supports natural phrasing)
    # + chain "and show my list"
    # -------------------------
    if t.startswith(("add", "create", "make")) or any(
        k in t for k in ["remind me to", "i need to", "i have to", "put", "add "]
    ):
        multi_items = _split_multi_items(raw)
        if multi_items:
            acts: List[Parsed] = [("add_many", {"items": multi_items})]
            if wants_show_after:
                acts.append(("list", {"filter": "all", "priority": None, "sort_by": None, "sort_dir": None, "limit": None}))
            return acts

        title = None
        desc = None

        m_title = re.search(
            r"(?:title)\s*(?::|=|is|should be)\s*['\"]?(.+?)['\"]?(?:\s+(?:and\s+)?(?:desc|description|details)\s*(?::|=|is|should be)\s*|$)",
            raw,
            flags=re.I,
        )
        m_desc = re.search(
            r"(?:desc|description|details)\s*(?::|=|is|should be)\s*['\"]?(.+?)['\"]?$",
            raw,
            flags=re.I,
        )
        if m_title:
            title = m_title.group(1).strip()
        if m_desc:
            desc = m_desc.group(1).strip()

        if not title:
            m = re.search(r"remind me to\s+(.+)$", raw, flags=re.I)
            if m:
                title = m.group(1).strip()

        if not title and any(k in t for k in ["i need to", "i have to"]):
            m = re.search(r"(?:i need to|i have to)\s+(.+)$", raw, flags=re.I)
            if m:
                title = m.group(1).strip()

        if not title and "add" in t:
            if ":" in raw:
                title = raw.split(":", 1)[1].strip().strip("'\"")
            else:
                m = re.search(
                    r"\badd\b\s+['\"]?(.+?)['\"]?(?:\s+to\s+my\s+todo\s+list)?$",
                    raw,
                    flags=re.I,
                )
                if m:
                    title = m.group(1).strip().strip("'\"")

        acts: List[Parsed] = [("add", {"title": title or "", "description": desc})]
        if wants_show_after:
            acts.append(("list", {"filter": "all", "priority": None, "sort_by": None, "sort_dir": None, "limit": None}))
        return acts

    # -------------------------
    # Status updates (existing + improved)
    # Now also covers: "task 3 is done" already above
    # -------------------------
    if t.startswith(
        ("mark", "complete", "uncomplete", "incomplete", "reopen", "toggle")
    ) or "mark all todos as completed" in t:
        if "mark all" in t and ("completed" in t or "done" in t):
            return [("complete_all", {"completed": True})]
        if "mark all" in t and ("pending" in t or "incomplete" in t or "reopen" in t):
            return [("complete_all", {"completed": False})]

        local_nos = _extract_ranges_and_lists(t)
        if not local_nos:
            ordref = _extract_ordinal_refs(t)
            if ordref:
                return [
                    (
                        "status_by_ordinal",
                        {
                            "ordinal": ordref,
                            "mode": "toggle" if t.startswith("toggle") else "set",
                            "completed": None,
                        },
                    )
                ]
            return [("clarify", {"message": "Which todo do you want to mark done/undone?"})]

        if t.startswith("toggle"):
            return [("toggle_many", {"local_nos": local_nos})]

        if "reopen" in t or "uncomplete" in t or "incomplete" in t:
            return [("complete_many", {"local_nos": local_nos, "completed": False})]

        return [("complete_many", {"local_nos": local_nos, "completed": True})]

    # -------------------------
    # Delete (supports: "delete 2", "delete todo 2", "remove task 3")
    # + chain "and show remaining todos"
    # -------------------------
    if t.startswith(("delete", "remove")):
        nums = _extract_ranges_and_lists(t)
        if nums:
            acts: List[Parsed] = [("delete_many", {"local_nos": nums})]
            if wants_show_after:
                acts.append(("list", {"filter": "all", "priority": None, "sort_by": None, "sort_dir": None, "limit": None}))
            return acts

        ordref = _extract_ordinal_refs(t)
        if ordref:
            acts2: List[Parsed] = [("delete_by_ordinal", {"ordinal": ordref})]
            if wants_show_after:
                acts2.append(("list", {"filter": "all", "priority": None, "sort_by": None, "sort_dir": None, "limit": None}))
            return acts2

        m = re.search(
            r"(?:delete|remove)\s+(?:the\s+)?(.+?)\s+(?:todo|task)\b", raw, flags=re.I
        )
        if m:
            acts3: List[Parsed] = [("delete_by_text", {"query": m.group(1).strip()})]
            if wants_show_after:
                acts3.append(("list", {"filter": "all", "priority": None, "sort_by": None, "sort_dir": None, "limit": None}))
            return acts3

        return [("clarify", {"message": "Which todo number do you want to delete? Example: Delete todo 3"})]

    # -------------------------
    # Update / Patch (same as your code + keeps "Add this description: X to todo 3")
    # -------------------------
    if t.startswith(("update", "patch", "edit", "change", "rename")):
        # "Add this description: X to todo 3"
        m_add_desc = re.search(
            r"(?:add|set)\s+(?:this\s+)?(?:desc|description|details)\s*(?::|=)?\s*['\"]?(.+?)['\"]?\s+(?:to|for|in)\s+(?:todo|task)\s+(\d+)\b",
            raw,
            flags=re.I,
        )
        if m_add_desc:
            desc_text = m_add_desc.group(1).strip()
            local_no = int(m_add_desc.group(2))
            return [
                (
                    "patch_many",
                    {
                        "local_nos": [local_no],
                        "title": None,
                        "description": desc_text,
                        "completed": None,
                    },
                )
            ]

        segments = re.split(r"\b(?:and|,)\b", raw, flags=re.I)
        seg_actions: List[Parsed] = []

        for seg in segments:
            seg_t = seg.strip()
            if not seg_t:
                continue

            seg_lower = seg_t.lower()
            seg_nums = _extract_ranges_and_lists(seg_lower)
            if not seg_nums:
                continue

            # status update
            if (
                "status" in seg_lower
                or "completed" in seg_lower
                or "done" in seg_lower
                or "reopen" in seg_lower
            ):
                completed = True
                if (
                    "reopen" in seg_lower
                    or "pending" in seg_lower
                    or "incomplete" in seg_lower
                ):
                    completed = False
                seg_actions.append(
                    ("complete_many", {"local_nos": seg_nums, "completed": completed})
                )
                continue

            title = None
            desc = None
            completed_field: Optional[bool] = None

            m_title = re.search(
                r"(?:title)\s*(?::|=|to|is|as|should be)\s*['\"]?(.+?)['\"]?(?:\s+(?:and\s+)?(?:desc|description|details)\b|$)",
                seg_t,
                flags=re.I,
            )
            m_desc = re.search(
                r"(?:desc|description|details)\s*(?::|=|to|is|as|should be)\s*['\"]?(.+?)['\"]?$",
                seg_t,
                flags=re.I,
            )
            if m_title:
                title = m_title.group(1).strip()
            if m_desc:
                desc = m_desc.group(1).strip()

            if title is None and seg_lower.strip().startswith("rename"):
                m = re.search(
                    r"rename\s+(?:todo|task)?\s*\b(\d+)\b\s+(?:as|to)\s+['\"]?(.+?)['\"]?$",
                    seg_t,
                    flags=re.I,
                )
                if m:
                    seg_nums = [int(m.group(1))]
                    title = m.group(2).strip()

            seg_actions.append(
                (
                    "patch_many",
                    {
                        "local_nos": seg_nums,
                        "title": title,
                        "description": desc,
                        "completed": completed_field,
                    },
                )
            )

        if seg_actions:
            return seg_actions

        local_nos = _extract_ranges_and_lists(t)
        if not local_nos:
            ordref = _extract_ordinal_refs(t)
            if ordref:
                return [
                    (
                        "clarify",
                        {
                            "message": "Which fields should I update for that todo? (title / description / status)"
                        },
                    )
                ]
            return [
                (
                    "clarify",
                    {
                        "message": "Which todo do you want to update? Example: Update todo 3 title to 'Buy vegetables'"
                    },
                )
            ]

        title = None
        desc = None

        m_title = re.search(
            r"(?:title)\s*(?::|=|to|is|as|should be)\s*['\"]?(.+?)['\"]?(?:\s+(?:and\s+)?(?:desc|description|details)\b|$)",
            raw,
            flags=re.I,
        )
        m_desc = re.search(
            r"(?:desc|description|details)\s*(?::|=|to|is|as|should be)\s*['\"]?(.+?)['\"]?$",
            raw,
            flags=re.I,
        )
        if m_title:
            title = m_title.group(1).strip()
        if m_desc:
            desc = m_desc.group(1).strip()

        if desc is None and "more details" in t:
            return [
                (
                    "clarify",
                    {
                        "message": f"What description should I set for todo(s) {_human_list(local_nos)}?"
                    },
                )
            ]

        return [
            (
                "patch_many",
                {
                    "local_nos": local_nos,
                    "title": title,
                    "description": desc,
                    "completed": None,
                },
            )
        ]

    # -------------------------
    # Group by status
    # -------------------------
    if "group" in t and "status" in t:
        return [("group_by_status", {})]

    # -------------------------
    # Undo (common but not supported)
    # -------------------------
    if "undo" in t:
        return [("clarify", {"message": "Undo is not implemented yet. Tell me what to revert (e.g., 'reopen todo 3' or 'restore title of todo 2')."})]

    return [("unknown", {})]


# =========================================================
# Gemini fallback (ONLY when unknown)
# =========================================================
SYSTEM_INSTRUCTIONS = """
You are a TODO assistant. Convert the user's message into ONE JSON object only (no markdown).
IMPORTANT: The "id" values must be the user's LOCAL todo numbers (1..N), NOT database ids.

You may output ONE of these shapes:

1) Add single:
{"action":"add","title":"...","description":optional}

2) Add many:
{"action":"add_many","items":[{"title":"...","description":optional}, ...]}

3) List:
{"action":"list","filter":"all|completed|pending","priority":"high"|null,"sort_by":"created|status|priority"|null,"sort_dir":"asc|desc"|null}

4) Count:
{"action":"count","filter":"all|completed|pending"}

5) Summary:
{"action":"summary"}

6) Details:
{"action":"details","ids":[1,2]}

7) Update:
{"action":"update","ops":[{"id":3,"title":optional,"description":optional,"completed":optional}, ...]}

8) Status bulk:
{"action":"complete_all","completed":true|false}

9) Delete:
{"action":"delete","ids":[1,2]}
{"action":"delete_all"}
{"action":"delete_filtered","filter":"completed|pending"}

10) Search:
{"action":"search","query":"..."}

Rules:
- If unclear (e.g., "update todo", "delete that one", "mark it done"), output:
  {"action":"clarify","question":"..."}
Return JSON only.
""".strip()


def gemini_to_action(user_text: str) -> dict:
    api_key = getattr(settings, "gemini_api_key", None) or getattr(
        settings, "GEMINI_API_KEY", None
    )
    model_name = (
        getattr(settings, "gemini_model", None)
        or getattr(settings, "GEMINI_MODEL", None)
        or "gemini-1.5-flash"
    )

    if not api_key:
        raise HTTPException(
            status_code=500, detail="Gemini API key is missing (check settings/.env)."
        )

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    resp = model.generate_content(SYSTEM_INSTRUCTIONS + "\nUser: " + user_text)
    raw = (resp.text or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(raw)
    except Exception:
        return {"action": "unknown"}


def normalize_ai(ai: dict) -> List[Parsed]:
    act = (ai.get("action") or "unknown").lower()

    if act == "add":
        return [
            ("add", {"title": ai.get("title") or "", "description": ai.get("description")})
        ]

    if act == "add_many":
        items = ai.get("items") or []
        titles: List[str] = []
        for it in items:
            if isinstance(it, dict) and (it.get("title") or "").strip():
                titles.append((it.get("title") or "").strip())
        return (
            [("add_many", {"items": titles})]
            if titles
            else [("clarify", {"message": "What todos should I add?"})]
        )

    if act == "list":
        return [
            (
                "list",
                {
                    "filter": ai.get("filter", "all"),
                    "priority": ai.get("priority"),
                    "sort_by": ai.get("sort_by"),
                    "sort_dir": ai.get("sort_dir"),
                    "limit": None,
                },
            )
        ]

    if act == "count":
        return [("count", {"filter": ai.get("filter", "all")})]

    if act == "summary":
        return [("summary", {})]

    if act == "details":
        ids = ai.get("ids") or []
        if isinstance(ids, list) and ids:
            return [
                (
                    "details",
                    {
                        "local_nos": [
                            int(x) for x in ids if isinstance(x, int) and x > 0
                        ]
                    },
                )
            ]
        return [("clarify", {"message": "Which todo number do you want details for?"})]

    if act == "update":
        ops = ai.get("ops") or []
        parsed: List[Parsed] = []
        for op in ops:
            if not isinstance(op, dict):
                continue
            tid = op.get("id")
            if not isinstance(tid, int):
                continue
            parsed.append(
                (
                    "patch_many",
                    {
                        "local_nos": [tid],
                        "title": op.get("title"),
                        "description": op.get("description"),
                        "completed": op.get("completed"),
                    },
                )
            )
        return parsed or [("clarify", {"message": "Which todo do you want to update?"})]

    if act == "complete_all":
        return [("complete_all", {"completed": bool(ai.get("completed", True))})]

    if act == "delete":
        ids = ai.get("ids") or []
        ids2 = [int(x) for x in ids if isinstance(x, int) and x > 0]
        return (
            [("delete_many", {"local_nos": ids2})]
            if ids2
            else [("clarify", {"message": "Which todo number do you want to delete?"})]
        )

    if act == "delete_all":
        return [("delete_all", {})]

    if act == "delete_filtered":
        return [("delete_filtered", {"filter": ai.get("filter", "completed")})]

    if act == "search":
        return [("search", {"query": ai.get("query") or ""})]

    if act == "clarify":
        return [
            (
                "clarify",
                {"message": ai.get("question") or "Can you clarify what you want to do?"},
            )
        ]

    return [("unknown", {})]


# =========================================================
# Routes
# =========================================================
@router.get("/history")
def history(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    msgs = session.exec(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.id.asc())
    ).all()

    out = []
    for m in msgs:
        role = "assistant" if m.role in ["assistant", "bot"] else "user"
        out.append({"id": m.id, "role": role, "content": m.content})
    return out


def _apply_list_filters(q, flt: str, priority: Optional[str]):
    if flt == "completed":
        q = q.where(Todo.completed == True)  # noqa
    elif flt == "pending":
        q = q.where(Todo.completed == False)  # noqa

    if priority and _has_attr(Todo, "priority"):
        if priority == "high":
            q = q.where(Todo.priority <= 2)  # type: ignore[attr-defined]

    return q


def _apply_sort(q, sort_by: Optional[str], sort_dir: Optional[str]):
    direction = (sort_dir or "asc").lower()

    if sort_by == "priority" and _has_attr(Todo, "priority"):
        col = Todo.priority  # type: ignore[attr-defined]
    elif sort_by == "status":
        col = Todo.completed
    else:
        col = Todo.id

    if direction == "desc":
        q = q.order_by(col.desc())  # type: ignore
    else:
        q = q.order_by(col.asc())  # type: ignore
    return q


def _ordinal_to_local_no(session: Session, user_id: int, ordinal: int) -> Optional[int]:
    todos = _get_user_todos(session, user_id)
    if not todos:
        return None
    if ordinal < 0:
        idx = len(todos) + ordinal  # -1 => last
        if 0 <= idx < len(todos):
            return idx + 1
        return None
    if 1 <= ordinal <= len(todos):
        return ordinal
    return None


def _summary_text(session: Session, user_id: int) -> str:
    todos = _get_user_todos(session, user_id)
    total = len(todos)
    completed = len([t for t in todos if getattr(t, "completed", False)])
    pending = total - completed
    return (
        f"Summary:\n"
        f"- Total: {total}\n"
        f"- Completed: {completed}\n"
        f"- Pending: {pending}\n\n"
        f"{format_todos_for_user(session, user_id, todos)}"
    )


@router.post("/message", response_model=ChatOut)
def send_message(
    data: ChatIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Save user message
    session.add(ChatMessage(user_id=user.id, role="user", content=data.message))
    session.commit()

    # 1) Fast parser
    actions = parse_intent_fast(data.message)

    # 2) Gemini fallback ONLY if unknown
    if len(actions) == 1 and actions[0][0] == "unknown":
        try:
            ai = gemini_to_action(data.message)
            actions = normalize_ai(ai)
        except Exception:
            actions = [("unknown", {})]

    replies: List[str] = []

    for action, payload in actions:
        # -------------------------
        # Add single
        # -------------------------
        if action == "add":
            title = (payload.get("title") or "").strip()
            desc = payload.get("description")

            if not title:
                replies.append("Please provide a title. Example: Add buy groceries")
                continue

            todo = Todo(user_id=user.id, title=title, description=desc)

            session.add(todo)
            session.commit()
            session.refresh(todo)

            local_no = len(_get_user_todos(session, user.id))
            msg = f"✅ Added Todo {local_no}\nTitle: {todo.title}"
            if getattr(todo, "description", None):
                msg += f"\nDescription: {todo.description}"
            replies.append(msg)
            continue

        # -------------------------
        # Add many
        # -------------------------
        if action == "add_many":
            items = payload.get("items") or []
            if not isinstance(items, list) or not items:
                replies.append("What todos should I add?")
                continue

            added_nums: List[int] = []
            for it in items:
                title = str(it).strip()
                if not title:
                    continue
                todo = Todo(user_id=user.id, title=title, description=None)
                session.add(todo)
                session.commit()
                session.refresh(todo)
                added_nums.append(len(_get_user_todos(session, user.id)))

            if not added_nums:
                replies.append("I could not find valid todo titles to add.")
            else:
                replies.append(f"✅ Added {len(added_nums)} todos: {_human_list(added_nums)}")
            continue

        # -------------------------
        # List (now supports optional limit)
        # -------------------------
        if action == "list":
            flt = payload.get("filter", "all")
            priority = payload.get("priority")
            sort_by = payload.get("sort_by")
            sort_dir = payload.get("sort_dir")
            limit = payload.get("limit")

            q = select(Todo).where(Todo.user_id == user.id)
            q = _apply_list_filters(q, flt, priority)
            if sort_by:
                q = _apply_sort(q, sort_by, sort_dir)
            else:
                q = q.order_by(Todo.id.asc())

            todos = session.exec(q).all()
            if isinstance(limit, int) and limit > 0:
                todos = todos[:limit]

            replies.append(format_todos_for_user(session, user.id, todos))
            continue

        # -------------------------
        # Group by status
        # -------------------------
        if action == "group_by_status":
            todos = _get_user_todos(session, user.id)
            done = [t for t in todos if getattr(t, "completed", False)]
            pending = [t for t in todos if not getattr(t, "completed", False)]
            replies.append(
                "Pending:\n"
                + (format_todos_for_user(session, user.id, pending) if pending else "No pending todos.")
            )
            replies.append(
                "Completed:\n"
                + (format_todos_for_user(session, user.id, done) if done else "No completed todos.")
            )
            continue

        # -------------------------
        # Count
        # -------------------------
        if action == "count":
            flt = payload.get("filter", "all")
            todos = _get_user_todos(session, user.id)
            if flt == "completed":
                n = len([t for t in todos if getattr(t, "completed", False)])
                replies.append(f"📌 Completed todos: {n}")
            elif flt == "pending":
                n = len([t for t in todos if not getattr(t, "completed", False)])
                replies.append(f"📌 Pending todos: {n}")
            else:
                replies.append(f"📌 Total todos: {len(todos)}")
            continue

        # -------------------------
        # Summary
        # -------------------------
        if action == "summary":
            replies.append(_summary_text(session, user.id))
            continue

        # -------------------------
        # Details
        # -------------------------
        if action == "details":
            local_nos = payload.get("local_nos")
            ordinal = payload.get("ordinal")

            if ordinal is not None and isinstance(ordinal, int):
                local = _ordinal_to_local_no(session, user.id, ordinal)
                if not local:
                    replies.append("I could not find that todo.")
                    continue
                local_nos = [local]

            if not local_nos:
                replies.append("Which todo number do you want details for?")
                continue

            db_ids = _resolve_many_local_to_db_ids(session, user.id, list(map(int, local_nos)))
            if not db_ids:
                replies.append("No matching todos found.")
                continue

            found: List[Todo] = []
            for db_id in db_ids:
                todo = session.get(Todo, db_id)
                if todo and todo.user_id == user.id:
                    found.append(todo)

            replies.append(format_todos_for_user(session, user.id, found))
            continue

        # -------------------------
        # Search
        # -------------------------
        if action == "search":
            qtext = (payload.get("query") or "").strip()
            if not qtext:
                replies.append("What should I search for? Example: Search todos containing 'meeting'")
                continue

            q = (
                select(Todo)
                .where(Todo.user_id == user.id)
                .where(
                    or_(
                        Todo.title.ilike(f"%{qtext}%"),
                        Todo.description.ilike(f"%{qtext}%"),  # type: ignore
                    )
                )
                .order_by(Todo.id.asc())
            )

            todos = session.exec(q).all()
            if not todos:
                replies.append(f"No todos matched: {qtext}")
            else:
                replies.append(
                    f"Search results for '{qtext}':\n" + format_todos_for_user(session, user.id, todos)
                )
            continue

        # -------------------------
        # Patch many
        # -------------------------
        if action == "patch_many":
            local_nos: List[int] = payload.get("local_nos") or []
            if not local_nos:
                replies.append("Which todo do you want to update? Example: Update todo 3 title to 'Buy vegetables'")
                continue

            title = payload.get("title")
            desc = payload.get("description")
            completed = payload.get("completed")

            if title is None and desc is None and completed is None:
                replies.append(
                    f"What should I update for todo(s) {_human_list(local_nos)}? (title / description / status)"
                )
                continue

            db_ids = _resolve_many_local_to_db_ids(session, user.id, local_nos)
            if not db_ids:
                replies.append("No matching todos found.")
                continue

            updated: List[Todo] = []
            for db_id in db_ids:
                todo = session.get(Todo, db_id)
                if not todo or todo.user_id != user.id:
                    continue

                if title is not None:
                    new_title = str(title).strip()
                    if new_title:
                        todo.title = new_title

                if desc is not None:
                    new_desc = str(desc).strip()
                    todo.description = new_desc if new_desc else None

                if completed is not None:
                    todo.completed = bool(completed)

                session.add(todo)
                updated.append(todo)

            session.commit()

            if not updated:
                replies.append("No todos were updated.")
            else:
                replies.append("✅ Updated:\n" + format_todos_for_user(session, user.id, updated))
            continue

        # -------------------------
        # Complete many / Toggle many / Complete all
        # -------------------------
        if action == "complete_many":
            local_nos: List[int] = payload.get("local_nos") or []
            if not local_nos:
                replies.append("Which todo do you want to mark done/undone?")
                continue

            db_ids = _resolve_many_local_to_db_ids(session, user.id, local_nos)
            if not db_ids:
                replies.append("No matching todos found.")
                continue

            new_val = bool(payload.get("completed", True))
            changed: List[Todo] = []
            for db_id in db_ids:
                todo = session.get(Todo, db_id)
                if todo and todo.user_id == user.id:
                    todo.completed = new_val
                    session.add(todo)
                    changed.append(todo)
            session.commit()
            replies.append("✅ Updated status:\n" + format_todos_for_user(session, user.id, changed))
            continue

        if action == "toggle_many":
            local_nos: List[int] = payload.get("local_nos") or []
            if not local_nos:
                replies.append("Which todo do you want to toggle?")
                continue

            db_ids = _resolve_many_local_to_db_ids(session, user.id, local_nos)
            if not db_ids:
                replies.append("No matching todos found.")
                continue

            changed: List[Todo] = []
            for db_id in db_ids:
                todo = session.get(Todo, db_id)
                if todo and todo.user_id == user.id:
                    todo.completed = not bool(todo.completed)
                    session.add(todo)
                    changed.append(todo)
            session.commit()
            replies.append("✅ Toggled status:\n" + format_todos_for_user(session, user.id, changed))
            continue

        if action == "complete_all":
            todos = _get_user_todos(session, user.id)
            desired = bool(payload.get("completed", True))
            for todo in todos:
                todo.completed = desired
                session.add(todo)
            session.commit()
            replies.append(f"✅ Marked all todos as {'completed' if desired else 'pending'}.")
            continue

        # -------------------------
        # Delete many / ordinal / text / filtered / all
        # -------------------------
        if action == "delete_many":
            local_nos: List[int] = payload.get("local_nos") or []
            if not local_nos:
                replies.append("Which todo number do you want to delete? Example: Delete todo 3")
                continue

            all_todos = _get_user_todos(session, user.id)
            local_map = {t.id: i + 1 for i, t in enumerate(all_todos)}

            db_ids = _resolve_many_local_to_db_ids(session, user.id, local_nos)
            if not db_ids:
                replies.append("No matching todos found.")
                continue

            deleted_local: List[int] = []
            for db_id in db_ids:
                todo = session.get(Todo, db_id)
                if todo and todo.user_id == user.id:
                    deleted_local.append(local_map.get(todo.id, -1))
                    session.delete(todo)

            session.commit()

            deleted_local = [x for x in deleted_local if x > 0]
            if deleted_local:
                replies.append(f"🗑️ Deleted todo(s): {_human_list(deleted_local)}")
            else:
                replies.append("No todos were deleted.")
            continue

        if action == "delete_by_ordinal":
            ordinal = payload.get("ordinal")
            local = (
                _ordinal_to_local_no(session, user.id, int(ordinal))
                if isinstance(ordinal, int)
                else None
            )
            if not local:
                replies.append("I could not find that todo.")
                continue

            db_id = _resolve_local_to_db_id(session, user.id, local)
            todo = session.get(Todo, db_id) if db_id else None
            if not todo or todo.user_id != user.id:
                replies.append("Todo not found.")
                continue
            session.delete(todo)
            session.commit()
            replies.append(f"🗑️ Deleted Todo {local}.")
            continue

        if action == "delete_by_text":
            qtext = (payload.get("query") or "").strip()
            if not qtext:
                replies.append("Which todo should I delete? Example: Delete the grocery todo")
                continue

            q = (
                select(Todo)
                .where(Todo.user_id == user.id)
                .where(
                    or_(
                        Todo.title.ilike(f"%{qtext}%"),
                        Todo.description.ilike(f"%{qtext}%"),  # type: ignore
                    )
                )
                .order_by(Todo.id.asc())
            )
            todos = session.exec(q).all()

            if not todos:
                replies.append(f"No todos matched: {qtext}")
                continue

            all_todos = _get_user_todos(session, user.id)
            local_map = {t.id: i + 1 for i, t in enumerate(all_todos)}

            deleted_local: List[int] = []
            for td in todos:
                deleted_local.append(local_map.get(td.id, -1))
                session.delete(td)

            session.commit()

            deleted_local = [x for x in deleted_local if x > 0]
            replies.append(f"🗑️ Deleted todo(s): {_human_list(deleted_local)}")
            continue

        if action == "delete_filtered":
            flt = payload.get("filter", "completed")

            q = select(Todo).where(Todo.user_id == user.id)
            if flt == "completed":
                q = q.where(Todo.completed == True)  # noqa
            elif flt == "pending":
                q = q.where(Todo.completed == False)  # noqa

            todos = session.exec(q).all()
            if not todos:
                replies.append(f"No {flt} todos to delete.")
                continue

            for td in todos:
                session.delete(td)
            session.commit()
            replies.append(f"🗑️ Deleted all {flt} todos ({len(todos)}).")
            continue

        if action == "delete_all":
            session.exec(delete(Todo).where(Todo.user_id == user.id))
            session.commit()
            replies.append("🗑️ Deleted all todos.")
            continue

        # -------------------------
        # Clarify / Unknown
        # -------------------------
        if action == "clarify":
            replies.append(payload.get("message") or "Can you clarify what you want to do?")
            continue

        if action == "unknown":
            replies.append(
                "I can help with todos. Try:\n"
                "- Todo 1 is completed / Todo 1 is incomplete\n"
                "- I've completed todo 3\n"
                "- Add a todo: buy groceries\n"
                "- Add 3 todos: buy milk, buy eggs, buy bread\n"
                "- Show my todos / Show completed / Show pending\n"
                "- Show todo 3 / Show todo number 3\n"
                "- Show first 5 todos / Show my latest todo\n"
                "- Which todo has title groceries?\n"
                "- Add this description: buy xyz to todo 3\n"
                "- Update todo 3 title to 'Buy vegetables'\n"
                "- Mark todo 3 as completed / Reopen todo 8 / Toggle 2\n"
                "- Delete 2 / Delete todo 2 / Delete todos 1 to 4\n"
                "- Delete all completed / Delete all todos\n"
                "- Find todo related to gym\n"
                "- Delete todo 2 and show remaining todos"
            )
            continue

    reply = "\n\n".join([r for r in replies if r.strip()]) or "Done."

    session.add(ChatMessage(user_id=user.id, role="assistant", content=reply))
    session.commit()

    return ChatOut(message=reply)


@router.delete("/clear")
def clear_chat(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    session.exec(delete(ChatMessage).where(ChatMessage.user_id == user.id))
    session.commit()
    return {"detail": "Chat cleared."}