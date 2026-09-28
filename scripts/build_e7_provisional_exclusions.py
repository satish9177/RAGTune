"""Build provisional query exclusions for E7 reranker training.

Conservatively excludes all 11 queries flagged in E7_QUERY_POSITIVE_AUDIT.json
pending Satish's explicit human audit.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    audit_file = root / "data" / "training" / "E7_QUERY_POSITIVE_AUDIT.json"
    out_file = root / "data" / "training" / "E7_PROVISIONAL_QUERY_EXCLUSIONS.json"

    with open(audit_file, "r", encoding="utf-8") as f:
        audit_data = json.load(f)

    excluded_items = audit_data.get("audit_items", [])
    excluded_query_ids = [item["query_id"] for item in excluded_items]
    assert len(excluded_query_ids) == 11, f"Expected 11 excluded queries, got {len(excluded_query_ids)}"

    payload = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "PROVISIONALLY_EXCLUDED_PENDING_HUMAN_AUDIT",
        "description": "Queries conservatively excluded from provisional E7 domain reranker training until human sign-off.",
        "source_audit": "data/training/E7_QUERY_POSITIVE_AUDIT.json",
        "total_excluded_queries": len(excluded_query_ids),
        "excluded_query_ids": excluded_query_ids,
        "query_details": [
            {
                "query_id": item["query_id"],
                "domain": item["domain"],
                "typology": item["typology"],
                "query_text": item["query_text"],
                "quality_flags": item.get("quality_flags", []),
                "positive_chunk_id": item.get("positive_chunk_id"),
                "positive_source_file": item.get("positive_source_file"),
            }
            for item in excluded_items
        ],
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Persisted {len(excluded_query_ids)} provisional exclusions to: {out_file}")


if __name__ == "__main__":
    main()
