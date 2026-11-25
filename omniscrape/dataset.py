import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import pandas as pd


class DatasetExporter:
    """
    Transforms raw scraped records into high-quality, normalized datasets
    and exports them to CSV, JSON, and JSONL formats with complete data hygiene.
    """

    def __init__(
        self,
        deduplicate: bool = True,
        dedup_keys: Optional[List[str]] = None,
        add_metadata: bool = True,
    ):
        self.deduplicate = deduplicate
        self.dedup_keys = dedup_keys or ["link", "url", "title", "name", "headline"]
        self.add_metadata = add_metadata

    def flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
        """Flatten nested dictionaries into single-level dot/underscore keys."""
        items: List[tuple] = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self.flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                # If list of primitives, join by comma; if list of dicts, serialize to json string
                if all(isinstance(i, (str, int, float, bool)) for i in v):
                    items.append((new_key, ", ".join(str(i) for i in v)))
                else:
                    items.append((new_key, json.dumps(v, ensure_ascii=False)))
            else:
                items.append((new_key, v))
        return dict(items)

    def clean_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Clean string values, strip non-printable characters and control chars."""
        cleaned: Dict[str, Any] = {}
        for k, v in record.items():
            if isinstance(v, str):
                # Remove control characters except standard space and newline
                v_clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v)
                # Normalize line breaks for CSV safety
                v_clean = re.sub(r"\r\n|\r", "\n", v_clean)
                cleaned[k] = v_clean.strip()
            elif v is None:
                cleaned[k] = ""
            else:
                cleaned[k] = v
        return cleaned

    def process_records(
        self,
        records: List[Dict[str, Any]],
        source_url: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Normalize, flatten, enrich with metadata, and deduplicate records.
        """
        if not records:
            return []

        timestamp = datetime.now(timezone.utc).isoformat()
        processed: List[Dict[str, Any]] = []
        seen_keys: set = set()

        for idx, raw in enumerate(records):
            flattened = self.flatten_dict(raw)
            cleaned = self.clean_record(flattened)

            if not any(str(val).strip() for val in cleaned.values()):
                continue

            # Deduplication
            if self.deduplicate:
                dedup_val = None
                for k in self.dedup_keys:
                    if cleaned.get(k):
                        dedup_val = f"{k}:{cleaned[k]}"
                        break
                if not dedup_val:
                    # Fallback hash of entire record content
                    content_str = json.dumps(cleaned, sort_keys=True)
                    dedup_val = hashlib.sha256(content_str.encode()).hexdigest()

                if dedup_val in seen_keys:
                    continue
                seen_keys.add(dedup_val)

            # Metadata provenance
            if self.add_metadata:
                cleaned["_row_id"] = len(processed) + 1
                if source_url:
                    cleaned["_source_url"] = source_url
                cleaned["_scraped_at"] = timestamp

            processed.append(cleaned)

        return processed

    def to_dataframe(self, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert list of records to a cleaned pandas DataFrame."""
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        # Reorder columns so primary identifiers and titles are first, metadata last
        primary_order = ["_row_id", "title", "name", "headline", "price", "currency", "rating", "link", "url", "description", "image_url"]
        meta_cols = ["_source_url", "_scraped_at"]
        
        all_cols = list(df.columns)
        first_cols = [c for c in primary_order if c in all_cols]
        last_cols = [c for c in meta_cols if c in all_cols and c not in first_cols]
        middle_cols = [c for c in all_cols if c not in first_cols and c not in last_cols]
        
        final_cols = first_cols + middle_cols + last_cols
        return df[final_cols]

    def save_csv(
        self,
        records: List[Dict[str, Any]],
        output_path: str,
        source_url: str = "",
    ) -> str:
        """
        Save records to CSV with UTF-8 BOM encoding for complete Excel and ML library compatibility.
        """
        processed = self.process_records(records, source_url=source_url)
        if not processed:
            raise ValueError("No valid records to save.")

        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        df = self.to_dataframe(processed)
        
        # Save using utf-8-sig (Excel friendly)
        df.to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig",
            quoting=csv.QUOTE_MINIMAL,
        )

        return os.path.abspath(output_path)

    def save_json(
        self,
        records: List[Dict[str, Any]],
        output_path: str,
        source_url: str = "",
        jsonl: bool = False,
    ) -> str:
        """Save records to JSON or JSONL format."""
        processed = self.process_records(records, source_url=source_url)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        if jsonl:
            with open(output_path, "w", encoding="utf-8") as f:
                for r in processed:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(processed, f, ensure_ascii=False, indent=2)

        return os.path.abspath(output_path)

    def dataset_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generate dataset quality and shape summary."""
        if df.empty:
            return {"total_rows": 0, "total_columns": 0, "columns": []}

        summary = {
            "total_rows": int(len(df)),
            "total_columns": int(len(df.columns)),
            "columns": list(df.columns),
            "missing_values": {col: int(df[col].isna().sum() + (df[col] == "").sum()) for col in df.columns},
            "sample_records": df.head(3).to_dict(orient="records"),
        }
        return summary
