#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the TUI sparkline generation functions."""

import pytest

# Skip this module if textual is not installed
pytest.importorskip("textual")

from core.tui.app import make_sparkline, SPARKLINE_CHARS


class TestMakeSparklineBasic:
    """Tests for basic sparkline generation."""

    def test_make_sparkline_basic(self):
        """Basic sparkline from values."""
        values = [1, 2, 3, 4, 5, 6, 7, 8]
        result = make_sparkline(values)

        assert len(result) == 8
        # Should use the full range of characters
        assert result[0] == SPARKLINE_CHARS[0]  # Lowest
        assert result[-1] == SPARKLINE_CHARS[7]  # Highest

    def test_make_sparkline_increasing_values(self):
        """Sparkline shows increasing pattern."""
        values = [0, 25, 50, 75, 100]
        result = make_sparkline(values)

        # Characters should increase from left to right
        for i in range(1, len(result)):
            assert result[i] >= result[i-1]

    def test_make_sparkline_decreasing_values(self):
        """Sparkline shows decreasing pattern."""
        values = [100, 75, 50, 25, 0]
        result = make_sparkline(values)

        # Characters should decrease from left to right
        for i in range(1, len(result)):
            assert result[i] <= result[i-1]

    def test_make_sparkline_uses_unicode_blocks(self):
        """Sparkline uses the expected Unicode block characters."""
        values = [1, 2, 3, 4]
        result = make_sparkline(values)

        # All characters should be from the sparkline charset
        for char in result:
            assert char in SPARKLINE_CHARS


class TestMakeSparklineEmpty:
    """Tests for handling empty input."""

    def test_make_sparkline_empty(self):
        """Handle empty list."""
        result = make_sparkline([])
        assert result == ""

    def test_make_sparkline_none_values_converted(self):
        """Values list must contain numbers."""
        # This would raise if passed None values
        # Testing that valid float list works
        values = [0.0, 0.0, 0.0]
        result = make_sparkline(values)
        assert len(result) == 3


class TestMakeSparklineSingle:
    """Tests for handling single value."""

    def test_make_sparkline_single(self):
        """Handle single value."""
        result = make_sparkline([42])

        # Single value should show middle height (since range=0)
        assert len(result) == 1
        assert result == SPARKLINE_CHARS[3]

    def test_make_sparkline_single_zero(self):
        """Handle single zero value."""
        result = make_sparkline([0])
        assert len(result) == 1
        assert result == SPARKLINE_CHARS[3]


class TestMakeSparklineAllSame:
    """Tests for handling all same values."""

    def test_make_sparkline_all_same(self):
        """Handle all same values."""
        result = make_sparkline([5, 5, 5, 5, 5])

        # All same values = middle height for all
        assert len(result) == 5
        assert result == SPARKLINE_CHARS[3] * 5

    def test_make_sparkline_all_zeros(self):
        """Handle all zero values."""
        result = make_sparkline([0, 0, 0, 0])
        assert len(result) == 4
        # All same (zero) = middle height
        assert result == SPARKLINE_CHARS[3] * 4

    def test_make_sparkline_all_large(self):
        """Handle all large same values."""
        result = make_sparkline([1000, 1000, 1000])
        assert len(result) == 3
        assert result == SPARKLINE_CHARS[3] * 3


class TestMakeSparklineWithWidth:
    """Tests for width parameter."""

    def test_make_sparkline_with_width_truncates(self):
        """Specify output width truncates to most recent."""
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = make_sparkline(values, width=5)

        # Should take last 5 values: 6, 7, 8, 9, 10
        assert len(result) == 5

    def test_make_sparkline_width_smaller_than_data(self):
        """Width smaller than data takes most recent."""
        values = [10, 20, 30, 40, 50]  # 5 values
        result = make_sparkline(values, width=3)

        # Should take last 3: 30, 40, 50
        assert len(result) == 3
        # Should show increasing pattern
        assert result[0] <= result[1] <= result[2]

    def test_make_sparkline_width_larger_than_data(self):
        """Width larger than data returns all data."""
        values = [1, 2, 3]
        result = make_sparkline(values, width=10)

        # Only 3 values, so result is 3 long (no padding)
        assert len(result) == 3

    def test_make_sparkline_width_equal_to_data(self):
        """Width equal to data size returns same length."""
        values = [1, 2, 3, 4, 5]
        result = make_sparkline(values, width=5)
        assert len(result) == 5

    def test_make_sparkline_width_zero(self):
        """Width=0 returns full sparkline."""
        values = [1, 2, 3, 4, 5, 6, 7, 8]
        result = make_sparkline(values, width=0)
        assert len(result) == 8


class TestMakeSparklineEdgeCases:
    """Tests for edge cases."""

    def test_make_sparkline_float_values(self):
        """Handle floating point values."""
        values = [0.1, 0.5, 1.0, 1.5, 2.0]
        result = make_sparkline(values)
        assert len(result) == 5

    def test_make_sparkline_negative_values(self):
        """Handle negative values."""
        values = [-10, -5, 0, 5, 10]
        result = make_sparkline(values)

        assert len(result) == 5
        # Should show increasing pattern
        assert result[0] == SPARKLINE_CHARS[0]
        assert result[-1] == SPARKLINE_CHARS[7]

    def test_make_sparkline_mixed_large_range(self):
        """Handle large value range."""
        values = [0, 1000000]
        result = make_sparkline(values)

        assert len(result) == 2
        assert result[0] == SPARKLINE_CHARS[0]
        assert result[1] == SPARKLINE_CHARS[7]

    def test_make_sparkline_very_small_differences(self):
        """Handle very small differences between values."""
        values = [1.0, 1.001, 1.002, 1.003]
        result = make_sparkline(values)

        assert len(result) == 4
        # Should still show progression
        assert result[0] == SPARKLINE_CHARS[0]
        assert result[-1] == SPARKLINE_CHARS[7]

    def test_make_sparkline_two_values(self):
        """Handle exactly two values."""
        values = [0, 100]
        result = make_sparkline(values)

        assert len(result) == 2
        assert result[0] == SPARKLINE_CHARS[0]
        assert result[1] == SPARKLINE_CHARS[7]


class TestSparklineChars:
    """Tests for sparkline character set."""

    def test_sparkline_chars_count(self):
        """Verify we have 8 sparkline characters."""
        assert len(SPARKLINE_CHARS) == 8

    def test_sparkline_chars_unicode(self):
        """Verify sparkline chars are valid Unicode block characters."""
        # The sparkline characters should be in the Unicode block elements range
        for char in SPARKLINE_CHARS:
            # Block elements are in range U+2580 to U+259F
            code_point = ord(char)
            assert 0x2580 <= code_point <= 0x259F, f"Character {char} (U+{code_point:04X}) not in block elements range"
