"""Tests for cli_utils.py — terminal formatting utilities (0% baseline)."""

from agent_seal.cli_utils import ok, fail, warn, info, dim, bold, table, progress_bar, C


class TestAnsiColors:
    def test_ok_default_message(self):
        result = ok()
        assert C["green"] in result
        assert "OK" in result
        assert C["reset"] in result

    def test_ok_custom_message(self):
        result = ok("done")
        assert "done" in result

    def test_fail_default_message(self):
        result = fail()
        assert C["red"] in result
        assert "FAIL" in result
        assert C["reset"] in result

    def test_fail_custom_message(self):
        result = fail("error occurred")
        assert "error occurred" in result

    def test_warn_default_message(self):
        result = warn()
        assert C["yellow"] in result
        assert C["reset"] in result

    def test_warn_custom_message(self):
        result = warn("caution")
        assert "caution" in result

    def test_info_default_message(self):
        result = info()
        assert C["cyan"] in result
        assert C["reset"] in result

    def test_info_custom_message(self):
        result = info("details")
        assert "details" in result

    def test_dim_default_message(self):
        result = dim()
        assert C["dim"] in result
        assert C["reset"] in result

    def test_dim_custom_message(self):
        result = dim("subtle text")
        assert "subtle text" in result

    def test_bold_default_message(self):
        result = bold()
        assert C["bold"] in result
        assert C["reset"] in result

    def test_bold_custom_message(self):
        result = bold("important")
        assert "important" in result


class TestTable:
    def test_basic_table(self):
        headers = ["Name", "Age"]
        rows = [["Alice", "30"], ["Bob", "25"]]
        result = table(headers, rows)
        assert "Alice" in result
        assert "Bob" in result
        assert "Name" in result
        assert "Age" in result
        assert "─" in result

    def test_table_single_row(self):
        headers = ["Key", "Value"]
        rows = [["foo", "bar"]]
        result = table(headers, rows)
        assert "foo" in result
        assert "bar" in result

    def test_table_empty_rows_empty_headers(self):
        headers: list[str] = []
        rows: list[list[str]] = []
        result = table(headers, rows)
        # empty headers + rows should not crash
        assert isinstance(result, str)

    def test_table_uneven_rows_non_string_cells(self):
        headers = ["A", "B"]
        rows = [[1, 2], ["three", 4]]
        result = table(headers, rows)
        assert "1" in result
        assert "2" in result
        assert "three" in result

    def test_table_varying_widths(self):
        headers = ["X", "Y"]
        rows = [["a", "bbb"], ["cccc", "d"]]
        result = table(headers, rows)
        assert "a" in result
        assert "bbb" in result
        assert "cccc" in result

    def test_table_special_chars(self):
        headers = ["Item"]
        rows = [["héllo wörld"], [""], ["tab\there"]]
        result = table(headers, rows)
        assert "héllo" in result
        assert "tab" in result


class TestProgressBar:
    def test_zero_percent(self):
        result = progress_bar(0, 100)
        assert "[░" in result or "[" in result
        assert "0%" in result

    def test_hundred_percent(self):
        result = progress_bar(100, 100)
        assert "100%" in result

    def test_fifty_percent(self):
        result = progress_bar(50, 100)
        assert "50%" in result

    def test_overflow_clamped(self):
        result = progress_bar(150, 100)
        assert "100%" in result

    def test_zero_total_does_not_divide_by_zero(self):
        result = progress_bar(0, 0)
        assert "0%" in result or "100%" in result

    def test_partial_filled(self):
        result = progress_bar(1, 3)
        assert "%" in result

    def test_custom_width(self):
        result = progress_bar(50, 100, width=10)
        assert len(result) > 0


class TestColorDictionary:
    def test_has_all_expected_keys(self):
        expected = {"reset", "bold", "dim", "red", "green", "yellow", "blue", "cyan", "white"}
        assert expected.issubset(C.keys())

    def test_reset_is_valid_escape(self):
        assert C["reset"] == "\033[0m"

    def test_bold_is_valid_escape(self):
        assert C["bold"] == "\033[1m"

    def test_red_contains_31(self):
        assert "\033[31m" in C["red"]
