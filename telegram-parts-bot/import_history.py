"""Import old group history from a Telegram Desktop export (result.json).

Bots only see messages sent after they join, so use this once to load the past:
Telegram Desktop -> open the group -> ⋮ -> Export chat history -> format: JSON.

    python import_history.py path/to/result.json --chat-id -1001234567890

--chat-id must be the id the bot sees for the group (send /chatid in the group).
"""

import argparse
import json
from datetime import datetime, timezone

from parts import extract_part_numbers
from storage import Storage


def flatten_text(text) -> str:
    # Export stores formatted text as a list of strings and {"type":..., "text":...} entities.
    if isinstance(text, str):
        return text
    return "".join(t if isinstance(t, str) else t.get("text", "") for t in text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export_json")
    ap.add_argument("--chat-id", type=int, required=True)
    ap.add_argument("--db", default="parts.db")
    args = ap.parse_args()

    with open(args.export_json, encoding="utf-8") as f:
        export = json.load(f)

    db = Storage(args.db)
    messages = parts_total = 0
    for m in export.get("messages", []):
        if m.get("type") != "message":
            continue  # service messages (joins, pins...)
        text = flatten_text(m.get("text", ""))
        if text.startswith("/"):
            continue
        when = datetime.fromtimestamp(int(m["date_unixtime"]), timezone.utc)
        from_id = m.get("from_id") or ""
        user_id = int(from_id[4:]) if from_id.startswith("user") else None
        parts = extract_part_numbers(text)
        db.save_message(args.chat_id, m["id"], user_id, m.get("from"), when, text, parts)
        messages += 1
        parts_total += len(parts)

    print(f"Imported {messages} messages with {parts_total} part number requests into {args.db}")


if __name__ == "__main__":
    main()
