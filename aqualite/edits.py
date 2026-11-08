"""Edit by voice: in Command Mode with nothing selected, "delete that last sentence" or "change Friday to Thursday"
edits the text that's already in the box.

The AI sees the text right before your cursor and answers with small edits: {"old": exact existing text,
"new": replacement}. Each edit is applied with the keyboard, relative to the cursor: Left to the end of the old
text, Shift+Left over it, paste the new text, Right back to where you were. The old text has to appear in the
box exactly as quoted, or nothing is touched.
"""
import json
import re

from .instant import presses

BOX_CHARS = 3000    # how much text before the cursor the AI gets to see


class EditError(Exception):
    pass


def parse_answer(out):
    """The AI's JSON answer -> {"type": "edit", "edits": [(old, new), ...]} or {"type": "insert", "text": ...}.
    Plain text (no JSON at all) counts as text to insert, like Command Mode always did."""
    s = (out or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < i:
        if not s:
            raise EditError("empty answer")
        return {"type": "insert", "text": s}
    try:
        data = json.loads(s[i:j + 1])
    except ValueError as e:
        raise EditError(f"unreadable answer: {e}")
    kind = str(data.get("type", "")).lower()
    if kind == "insert":
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise EditError("nothing to insert")
        return {"type": "insert", "text": text}
    if kind == "edit":
        edits = []
        for e in data.get("edits") or []:
            old, new = e.get("old"), e.get("new", "")
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise EditError("malformed edit")
            if old != new:
                edits.append((old, new))
        if not edits:
            raise EditError("no changes")
        return {"type": "edit", "edits": edits}
    raise EditError(f"unknown answer type {kind!r}")


def plan(before, edits):
    """Turn edits into keyboard steps, relative to the cursor at the end of `before`.
    Returns (steps, result): steps = [(chars_after, chars_selected, new_text)], applied in order; result = the text
    before the cursor once they're done. Each edit is found in the text as it stands after the previous ones,
    taking the occurrence nearest the cursor."""
    text, steps = before, []
    for old, new in edits:
        at = text.rfind(old)
        if at < 0:
            raise EditError(f"couldn't find {old[:40]!r} in the text")
        end = at + len(old)
        steps.append((presses(text[end:]), presses(old), new))
        text = text[:at] + new + text[end:]
    return steps, text


def apply(steps, keys):
    """Run the steps. keys: object with left(n), right(n), select_left(n), put(text) (paste over the selection)
    and delete() (remove the selection)."""
    for after, sel, new in steps:
        keys.left(after)
        keys.select_left(sel)
        if new:
            keys.put(new)
        else:
            keys.delete()
        keys.right(after)
