import pandas as pd
import re
from pathlib import Path


class DRILoader:
    """
    Loads and provides structured access to Dietary Reference Intake (DRI) data.

    Features:
    - Parses human-readable entries like "30–35", "<10", ">20", "≤5"
    - Normalizes nutrient names
    - Retrieves DRI values for specific age/sex groups or all groups
    - Returns structured dicts with numeric range info and source references

    Source: Table E3.1.A4, 'Nutritional Goals for Each Age/Sex Group'
    """

    def _init_(self, data_path: str | Path):
        self.data_path = Path(data_path)
        self.dri_data = self._load_data()

    # ------------------------------------------------------------
    # Load & normalize the DRI table
    # ------------------------------------------------------------
    def _load_data(self) -> pd.DataFrame:
        """
        Load and clean the DRI dataset.
        Expected columns: Nutrient / Category, Unit, Source of Goal*, 1–3, 4–8 (F), etc.
        """
        df = pd.read_csv(self.data_path)
        df.columns = [col.strip() for col in df.columns]

        # Normalize nutrient names (for consistent querying)
        df["Nutrient / Category"] = df["Nutrient / Category"].str.strip().str.lower()

        # Map columns to age/sex ranges
        self.age_groups = self._extract_age_groups(df.columns)

        return df

    # ------------------------------------------------------------
    # Extract structured metadata for each age/sex column
    # ------------------------------------------------------------
    def _extract_age_groups(self, columns):
        """
        Parse and normalize age/sex columns.
        Example: "4–8 (F)" → {"age_range": (4, 8), "sex": "F"}
        """
        age_groups = {}
        for col in columns:
            match = re.match(r"(\d+)[–-](\d+)\s*\((M|F)\)", col)
            if match:
                start, end, sex = match.groups()
                age_groups[col] = {"age_range": (int(start), int(end)), "sex": sex}
            elif re.match(r"\d+–\d+", col):  # e.g. "1–3" (no sex distinction)
                start, end = re.findall(r"\d+", col)
                age_groups[col] = {"age_range": (int(start), int(end)), "sex": None}
        return age_groups

    # ------------------------------------------------------------
    # Find the right column for a given age/sex
    # ------------------------------------------------------------
    def _get_column_for_age_sex(self, age: int, sex: str) -> str | None:
        """
        Identify which column corresponds to a given age and sex.
        """
        sex = sex.upper() if sex else None
        for col, meta in self.age_groups.items():
            low, high = meta["age_range"]
            if low <= age <= high and (meta["sex"] == sex or meta["sex"] is None):
                return col
        return None

    # ------------------------------------------------------------
    # Core parser for raw DRI values (handles <, >, ranges, etc.)
    # ------------------------------------------------------------
    def _parse_dri_value(self, raw):
        """
        Parse raw DRI entries like "30–35", "<10", ">20", "≤5", "45"
        into structured numeric form.
        """
        if pd.isna(raw):
            return None

        raw = str(raw).strip()
        pattern_range = re.match(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)", raw)
        pattern_lt = re.match(r"^<\s*(\d+(?:\.\d+)?)", raw)
        pattern_le = re.match(r"^(?:≤|<=)\s*(\d+(?:\.\d+)?)", raw)
        pattern_gt = re.match(r"^>\s*(\d+(?:\.\d+)?)", raw)
        pattern_ge = re.match(r"^(?:≥|>=)\s*(\d+(?:\.\d+)?)", raw)
        pattern_num = re.match(r"^\d+(?:\.\d+)?$", raw)

        if pattern_range:
            lo, hi = map(float, pattern_range.groups())
            return {"raw": raw, "type": "range", "min": lo, "max": hi, "approx_value": (lo + hi) / 2}
        elif pattern_lt:
            val = float(pattern_lt.group(1))
            return {"raw": raw, "type": "lt", "min": None, "max": val, "approx_value": val}
        elif pattern_le:
            val = float(pattern_le.group(1))
            return {"raw": raw, "type": "lt_eq", "min": None, "max": val, "approx_value": val}
        elif pattern_gt:
            val = float(pattern_gt.group(1))
            return {"raw": raw, "type": "gt", "min": val, "max": None, "approx_value": val}
        elif pattern_ge:
            val = float(pattern_ge.group(1))
            return {"raw": raw, "type": "gt_eq", "min": val, "max": None, "approx_value": val}
        elif pattern_num:
            val = float(pattern_num.group(0))
            return {"raw": raw, "type": "eq", "min": val, "max": val, "approx_value": val}
        else:
            return {"raw": raw, "type": "unknown", "min": None, "max": None, "approx_value": None}

    # ------------------------------------------------------------
    # Retrieve one nutrient’s DRI value for a person
    # ------------------------------------------------------------
    def get_dri_value(self, nutrient: str, age: int, sex: str):
        """
        Retrieve the DRI value for a specific nutrient, age, and sex.
        Returns a structured dict with value info, units, and citation.
        """
        nutrient = nutrient.lower().strip()
        match_row = self.dri_data[self.dri_data["Nutrient / Category"] == nutrient]

        if match_row.empty:
            return None

        col = self._get_column_for_age_sex(age, sex)
        if not col:
            return None

        raw_value = match_row[col].values[0]
        parsed_value = self._parse_dri_value(raw_value)
        unit = match_row["Unit"].values[0]
        source = match_row.get("Source of Goal*", "DRI Table E3.1.A4") if "Source of Goal*" in match_row else "DRI Table E3.1.A4"

        citation = "DRI Table E3.1.A4, USDA Food Patterns (2020)"

        return {
            "nutrient": nutrient.title(),
            "recommended_intake": parsed_value,
            "unit": unit,
            "source": source,
            "citation": citation
        }

    # ------------------------------------------------------------
    # Retrieve all DRI values for a given demographic
    # ------------------------------------------------------------
    def get_all_dri_for_group(self, age: int, sex: str) -> dict:
        """
        Retrieve all nutrient goals for a given age/sex group.
        Returns a dict of nutrient: structured_value pairs.
        """
        col = self._get_column_for_age_sex(age, sex)
        if not col:
            return {}

        results = {}
        for _, row in self.dri_data.iterrows():
            nutrient = row["Nutrient / Category"].title()
            raw_value = row[col]
            parsed_value = self._parse_dri_value(raw_value)

            results[nutrient] = {
                "value": parsed_value,
                "unit": row["Unit"],
                "source": row.get("Source of Goal*", "DRI Table E3.1.A4"),
            }

        return results