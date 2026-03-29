# tests/test_field_translator.py
"""Tests for the authoritative field translation layer (COL-208)."""

import sys
sys.path.insert(0, ".")

import pytest

from src.server.domain.field_dictionaries import (
    ALL_FINANCIAL_FIELDS,
    BALANCE_SHEET_FIELDS,
    CASH_FLOW_FIELDS,
    CODED_FIELDS,
    CODED_FIELD_NAMES,
    COMMON_FIELDS,
    COMP_TYPE,
    DATE_FIELDS,
    END_DATE_PERIOD,
    END_TYPE,
    FINANCIAL_INDICATOR_FIELDS,
    INCOME_FIELDS,
    REPORT_TYPE,
    UPDATE_FLAG,
)
from src.server.domain.field_translator import (
    translate_financial_payload,
    translate_record,
    translate_records,
    translate_section,
)


# -------------------------------------------------------------------
# Dictionary integrity
# -------------------------------------------------------------------

class TestDictionaryIntegrity:
    """Ensure dictionaries are complete and non-empty."""

    def test_report_type_has_12_entries(self):
        assert len(REPORT_TYPE) == 12
        assert REPORT_TYPE["1"] == "合并报表"
        assert REPORT_TYPE["6"] == "母公司报表"

    def test_comp_type_has_4_entries(self):
        assert len(COMP_TYPE) == 4
        assert COMP_TYPE["2"] == "银行"
        assert COMP_TYPE["4"] == "证券"

    def test_update_flag(self):
        assert UPDATE_FLAG["1"] == "最新"

    def test_end_date_period(self):
        assert END_DATE_PERIOD["1231"] == "年报"
        assert END_DATE_PERIOD["0331"] == "一季报"
        assert END_DATE_PERIOD["0630"] == "中报"
        assert END_DATE_PERIOD["0930"] == "三季报"

    def test_common_fields(self):
        for key in ("ann_date", "f_ann_date", "end_date", "report_type",
                    "comp_type", "end_type", "update_flag", "ts_code"):
            assert key in COMMON_FIELDS, f"{key} missing from COMMON_FIELDS"

    def test_income_fields_key_metrics(self):
        for key in ("basic_eps", "total_revenue", "revenue",
                    "n_income", "n_income_attr_p", "operate_profit",
                    "total_profit", "rd_exp"):
            assert key in INCOME_FIELDS, f"{key} missing from INCOME_FIELDS"

    def test_balance_sheet_fields_key_metrics(self):
        for key in ("total_assets", "total_liab", "total_share",
                    "money_cap", "inventories", "goodwill"):
            assert key in BALANCE_SHEET_FIELDS, f"{key} missing from BALANCE_SHEET_FIELDS"

    def test_cash_flow_fields_key_metrics(self):
        for key in ("n_cashflow_act", "free_cashflow", "n_cashflow_inv_act",
                    "c_fr_sale_sg"):
            assert key in CASH_FLOW_FIELDS, f"{key} missing from CASH_FLOW_FIELDS"

    def test_coded_fields_registry(self):
        assert "report_type" in CODED_FIELDS
        assert "comp_type" in CODED_FIELDS
        assert "update_flag" in CODED_FIELDS

    def test_date_fields(self):
        assert DATE_FIELDS == {"ann_date", "f_ann_date", "end_date"}

    def test_all_financial_fields_union(self):
        # Should contain keys from all sub-dictionaries
        for key in INCOME_FIELDS:
            assert key in ALL_FINANCIAL_FIELDS
        for key in BALANCE_SHEET_FIELDS:
            assert key in ALL_FINANCIAL_FIELDS


# -------------------------------------------------------------------
# translate_record
# -------------------------------------------------------------------

class TestTranslateRecord:
    """Test single-record translation."""

    def test_report_type_translated(self):
        row = {"ts_code": "600519.SH", "report_type": "1", "comp_type": "1"}
        result = translate_record(row)
        assert result["report_type"] == "1"  # raw preserved
        assert result["report_type_label"] == "合并报表"
        assert result["comp_type_label"] == "一般工商业"

    def test_date_formatting(self):
        row = {"ann_date": "20250403", "f_ann_date": "20250403", "end_date": "20241231"}
        result = translate_record(row)
        assert result["ann_date"] == "2025-04-03"
        assert result["f_ann_date"] == "2025-04-03"
        assert result["end_date"] == "2024-12-31"

    def test_period_label_from_end_date(self):
        row = {"end_date": "20241231"}
        result = translate_record(row)
        assert result["report_period"] == "年报"

        row2 = {"end_date": "20240630"}
        result2 = translate_record(row2)
        assert result2["report_period"] == "中报"

    def test_field_name_added(self):
        row = {"basic_eps": 1.84, "revenue": 1000000}
        result = translate_record(row)
        assert result["basic_eps_name"] == "基本每股收益"
        assert result["revenue_name"] == "营业收入"

    def test_preserve_raw_false(self):
        row = {"report_type": "1", "comp_type": "2"}
        result = translate_record(row, preserve_raw=False)
        assert "report_type" not in result
        assert result["report_type_label"] == "合并报表"
        assert result["comp_type_label"] == "银行"

    def test_non_dict_passthrough(self):
        assert translate_record("not a dict") == "not a dict"
        assert translate_record(None) is None

    def test_unknown_report_type(self):
        row = {"report_type": "99"}
        result = translate_record(row)
        assert result["report_type"] == "99"
        assert result["report_type_label"] == "99"  # falls back to raw

    def test_none_value_not_translated(self):
        row = {"report_type": None, "comp_type": None}
        result = translate_record(row)
        assert "report_type_label" not in result
        assert "comp_type_label" not in result


# -------------------------------------------------------------------
# translate_records
# -------------------------------------------------------------------

class TestTranslateRecords:
    def test_list_of_dicts(self):
        rows = [
            {"report_type": "1", "comp_type": "2"},
            {"report_type": "6", "comp_type": "1"},
        ]
        result = translate_records(rows)
        assert len(result) == 2
        assert result[0]["report_type_label"] == "合并报表"
        assert result[1]["report_type_label"] == "母公司报表"

    def test_single_dict(self):
        result = translate_records({"report_type": "1"})
        assert result["report_type_label"] == "合并报表"

    def test_passthrough(self):
        assert translate_records("hello") == "hello"


# -------------------------------------------------------------------
# translate_section
# -------------------------------------------------------------------

class TestTranslateSection:
    def test_income_section(self):
        data = [{"basic_eps": 1.5, "revenue": 500000}]
        result = translate_section("income_statement", data)
        assert result[0]["basic_eps_name"] == "基本每股收益"
        assert result[0]["revenue_name"] == "营业收入"

    def test_unknown_section(self):
        data = [{"some_field": 42}]
        result = translate_section("unknown_section", data)
        assert isinstance(result, list)

    def test_dict_section(self):
        data = {"basic_eps": 1.5}
        result = translate_section("income_statement", data)
        assert result["basic_eps_name"] == "基本每股收益"


# -------------------------------------------------------------------
# translate_financial_payload
# -------------------------------------------------------------------

class TestTranslateFinancialPayload:
    def test_full_payload(self):
        payload = {
            "income_statement": [
                {
                    "ts_code": "600519.SH",
                    "ann_date": "20250403",
                    "end_date": "20241231",
                    "report_type": "1",
                    "comp_type": "1",
                    "basic_eps": 1.84,
                    "revenue": 1000000000,
                }
            ],
            "balance_sheet": [
                {
                    "ts_code": "600519.SH",
                    "end_date": "20241231",
                    "total_assets": 2000000000,
                    "total_liab": 500000000,
                }
            ],
            "cash_flow": [
                {
                    "ts_code": "600519.SH",
                    "end_date": "20241231",
                    "n_cashflow_act": 300000000,
                }
            ],
        }
        result = translate_financial_payload(payload)

        # Income section checks
        inc = result["income_statement"][0]
        assert inc["ann_date"] == "2025-04-03"
        assert inc["end_date"] == "2024-12-31"
        assert inc["report_type_label"] == "合并报表"
        assert inc["comp_type_label"] == "一般工商业"
        assert inc["report_period"] == "年报"
        assert inc["basic_eps_name"] == "基本每股收益"
        assert inc["revenue_name"] == "营业收入"

        # Balance sheet checks
        bs = result["balance_sheet"][0]
        assert bs["total_assets_name"] == "资产总计"
        assert bs["report_period"] == "年报"

        # Cash flow checks
        cf = result["cash_flow"][0]
        assert cf["n_cashflow_act_name"] == "经营活动产生的现金流量净额"

    def test_non_dict_passthrough(self):
        assert translate_financial_payload("not a dict") == "not a dict"
