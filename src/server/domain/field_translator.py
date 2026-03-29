# src/server/domain/field_translator.py
"""Translate raw financial-data fields into human-readable form.

Uses authoritative dictionaries from ``field_dictionaries.py`` (Tushare Pro docs).

Public API:
    translate_record     – translate a single dict row
    translate_records    – translate a list[dict]
    translate_section    – translate a named section (income/balance/cash)
    translate_financial_payload – translate full financial-statements payload
"""

from __future__ import annotations

from typing import Any

from src.server.domain.field_dictionaries import (
    ALL_FINANCIAL_FIELDS,
    BALANCE_SHEET_FIELDS,
    CASH_FLOW_FIELDS,
    CODED_FIELDS,
    CODED_FIELD_NAMES,
    COMMON_FIELDS,
    DATE_FIELDS,
    END_DATE_PERIOD,
    FINANCIAL_INDICATOR_FIELDS,
    INCOME_FIELDS,
)

# Map section name → field dictionary for section-level translation
_SECTION_FIELDS: dict[str, dict[str, str]] = {
    "income_statement": INCOME_FIELDS,
    "balance_sheet": BALANCE_SHEET_FIELDS,
    "cash_flow": CASH_FLOW_FIELDS,
    "cash_flow_statement": CASH_FLOW_FIELDS,
    "financial_indicators": FINANCIAL_INDICATOR_FIELDS,
    "fina_indicator": FINANCIAL_INDICATOR_FIELDS,
}


def _format_date(val: Any) -> str:
    """Convert YYYYMMDD string to YYYY-MM-DD, pass others through."""
    if val is None:
        return val
    s = str(val).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _translate_code(field_name: str, raw_value: Any) -> Any:
    """Translate coded value if mapping exists; else return raw."""
    if field_name not in CODED_FIELDS:
        return raw_value
    mapping = CODED_FIELDS[field_name]
    key = str(raw_value).strip() if raw_value is not None else ""
    return mapping.get(key, raw_value)


def _infer_period_label(end_date: str) -> str | None:
    """Derive report-period label from end_date suffix (e.g. 1231 → 年报)."""
    s = str(end_date).strip()
    if len(s) == 8 and s.isdigit():
        suffix = s[4:8]
        return END_DATE_PERIOD.get(suffix)
    return None


def translate_record(
    record: dict[str, Any],
    *,
    field_dict: dict[str, str] | None = None,
    preserve_raw: bool = True,
) -> dict[str, Any]:
    """Translate a single financial record.

    Parameters
    ----------
    record:
        Raw record from data adapter (keys are Tushare field names).
    field_dict:
        Optional override for which fields to translate.
        Defaults to ALL_FINANCIAL_FIELDS + COMMON_FIELDS.
    preserve_raw:
        If True, keep the original field alongside the translated one
        (e.g. ``report_type`` stays as-is, ``report_type_label`` is added).

    Returns
    -------
    dict with translated / augmented fields.
    """
    if not isinstance(record, dict):
        return record

    fields = field_dict or ALL_FINANCIAL_FIELDS
    result: dict[str, Any] = {}

    for key, value in record.items():
        # Always keep original key
        result[key] = value

        # Date formatting
        if key in DATE_FIELDS and value is not None:
            result[key] = _format_date(value)

        # Coded value → add human-readable label
        if key in CODED_FIELD_NAMES and value is not None:
            label = _translate_code(key, value)
            result[f"{key}_label"] = label
            if not preserve_raw:
                del result[key]

        # Field name → add Chinese label
        if key in fields:
            result[f"{key}_name"] = fields[key]

    # Derive period label from end_date if present
    end_date = record.get("end_date")
    if end_date:
        period_label = _infer_period_label(str(end_date))
        if period_label:
            result["report_period"] = period_label

    return result


def translate_records(
    records: list[dict[str, Any]] | dict[str, Any] | Any,
    *,
    field_dict: dict[str, str] | None = None,
    preserve_raw: bool = True,
) -> Any:
    """Translate a list of records, a single record, or pass through."""
    if isinstance(records, list):
        return [
            translate_record(r, field_dict=field_dict, preserve_raw=preserve_raw)
            for r in records
        ]
    if isinstance(records, dict):
        return translate_record(records, field_dict=field_dict, preserve_raw=preserve_raw)
    return records


def translate_section(
    section_name: str,
    data: Any,
    *,
    preserve_raw: bool = True,
) -> Any:
    """Translate a named section (income_statement, balance_sheet, etc.).

    Data can be:
    - list[dict] → translate each row
    - dict with nested data → translate the values
    - anything else → pass through
    """
    fd = _SECTION_FIELDS.get(section_name)
    if fd is None:
        # Unknown section, try generic translation
        return translate_records(data, preserve_raw=preserve_raw)

    if isinstance(data, list):
        return [
            translate_record(r, field_dict={**COMMON_FIELDS, **fd}, preserve_raw=preserve_raw)
            for r in data
        ]
    if isinstance(data, dict):
        return translate_record(data, field_dict={**COMMON_FIELDS, **fd}, preserve_raw=preserve_raw)
    return data


def translate_financial_payload(
    payload: dict[str, Any],
    *,
    preserve_raw: bool = True,
) -> dict[str, Any]:
    """Translate a full financial-statements payload (income + balance + cash_flow).

    The payload is expected to have keys like ``income_statement``,
    ``balance_sheet``, ``cash_flow``, etc.  Each section is translated
    using section-specific field dictionaries.
    """
    if not isinstance(payload, dict):
        return payload

    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _SECTION_FIELDS:
            result[key] = translate_section(key, value, preserve_raw=preserve_raw)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            # Generic list-of-dicts, translate with all fields
            result[key] = translate_records(value, preserve_raw=preserve_raw)
        else:
            result[key] = value

    return result
