#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for XML tag rendering in TUI display."""

import pytest


class TestRenderTags:
    """Tests for the render_tags function."""

    def test_system_reminder_collapses_to_indicator(self):
        """system-reminder tags should collapse to [dim][System context][/dim]."""
        from core.tui.tag_renderer import render_tags

        content = "<system-reminder>This is a long system context with lots of details about the environment and instructions.</system-reminder>"
        result = render_tags(content)
        assert result == "[dim][System context][/dim]"

    def test_system_reminder_multiline_collapses(self):
        """Multiline system-reminder tags should collapse properly."""
        from core.tui.tag_renderer import render_tags

        content = """<system-reminder>
Line 1
Line 2
Line 3
</system-reminder>"""
        result = render_tags(content)
        assert result == "[dim][System context][/dim]"

    def test_system_reminder_preserves_surrounding_content(self):
        """Content around system-reminder tags should be preserved."""
        from core.tui.tag_renderer import render_tags

        content = "Before <system-reminder>hidden</system-reminder> After"
        result = render_tags(content)
        assert result == "Before [dim][System context][/dim] After"

    def test_local_command_caveat_collapses(self):
        """local-command-caveat tags should collapse to [dim][Command context][/dim]."""
        from core.tui.tag_renderer import render_tags

        content = "<local-command-caveat>Some command context information</local-command-caveat>"
        result = render_tags(content)
        assert result == "[dim][Command context][/dim]"

    def test_command_name_renders_with_slash(self):
        """command-name tags should render as [bold magenta]/name[/bold magenta]."""
        from core.tui.tag_renderer import render_tags

        content = "<command-name>commit</command-name>"
        result = render_tags(content)
        assert result == "[bold magenta]/commit[/bold magenta]"

    def test_command_name_with_leading_slash(self):
        """command-name with leading slash should not double the slash."""
        from core.tui.tag_renderer import render_tags

        content = "<command-name>/review</command-name>"
        result = render_tags(content)
        assert result == "[bold magenta]/review[/bold magenta]"

    def test_tool_use_error_renders_with_error_prefix(self):
        """tool_use_error tags should render as [red]Error: MSG[/red]."""
        from core.tui.tag_renderer import render_tags

        content = "<tool_use_error>File not found</tool_use_error>"
        result = render_tags(content)
        assert result == "[red]Error: File not found[/red]"

    def test_unknown_tags_stripped(self):
        """Unknown tags should be stripped but content preserved."""
        from core.tui.tag_renderer import render_tags

        content = "<unknown_tag>content inside</unknown_tag>"
        result = render_tags(content)
        assert result == "content inside"

    def test_self_closing_tags_stripped(self):
        """Self-closing unknown tags should be stripped."""
        from core.tui.tag_renderer import render_tags

        content = "before <br/> after"
        result = render_tags(content)
        assert result == "before  after"

    def test_empty_content_returns_empty(self):
        """Empty content should return empty string."""
        from core.tui.tag_renderer import render_tags

        assert render_tags("") == ""

    def test_none_content_returns_none(self):
        """None content should return None."""
        from core.tui.tag_renderer import render_tags

        assert render_tags(None) is None

    def test_content_without_tags_unchanged(self):
        """Content without tags should pass through unchanged."""
        from core.tui.tag_renderer import render_tags

        content = "Just plain text with no tags at all"
        result = render_tags(content)
        assert result == content

    def test_multiple_different_tags(self):
        """Multiple different tag types should all be transformed."""
        from core.tui.tag_renderer import render_tags

        content = "Run <command-name>test</command-name> and check <tool_use_error>oops</tool_use_error>"
        result = render_tags(content)
        assert result == "Run [bold magenta]/test[/bold magenta] and check [red]Error: oops[/red]"

    def test_nested_content_after_tag_removal(self):
        """After tag removal, nested content should remain intact."""
        from core.tui.tag_renderer import render_tags

        content = "<wrapper>inner <command-name>cmd</command-name> text</wrapper>"
        result = render_tags(content)
        assert result == "inner [bold magenta]/cmd[/bold magenta] text"

    def test_preserves_rich_markup_in_content(self):
        """Existing Rich markup in content should be preserved."""
        from core.tui.tag_renderer import render_tags

        content = "[bold]Already styled[/bold] text"
        result = render_tags(content)
        assert result == "[bold]Already styled[/bold] text"


class TestCollapseSystemTags:
    """Tests for the collapse_system_tags function."""

    def test_removes_system_reminder_completely(self):
        """system-reminder tags should be removed entirely, not replaced."""
        from core.tui.tag_renderer import collapse_system_tags

        content = "<system-reminder>This whole thing should disappear</system-reminder>"
        result = collapse_system_tags(content)
        assert result == ""

    def test_removes_system_reminder_keeps_other_content(self):
        """Other content around system-reminder should be preserved."""
        from core.tui.tag_renderer import collapse_system_tags

        content = "Important: <system-reminder>hidden stuff</system-reminder>Continue here"
        result = collapse_system_tags(content)
        assert result == "Important: Continue here"

    def test_removes_trailing_whitespace_after_system_reminder(self):
        """Trailing whitespace after system-reminder should be cleaned up."""
        from core.tui.tag_renderer import collapse_system_tags

        content = "<system-reminder>context</system-reminder>   \nActual content"
        result = collapse_system_tags(content)
        assert result == "Actual content"

    def test_removes_multiline_system_reminder(self):
        """Multiline system-reminder should be completely removed."""
        from core.tui.tag_renderer import collapse_system_tags

        content = """Before
<system-reminder>
Line 1
Line 2
</system-reminder>
After"""
        result = collapse_system_tags(content)
        assert "Line 1" not in result
        assert "Line 2" not in result
        assert "Before" in result
        assert "After" in result

    def test_strips_result(self):
        """Result should be stripped of leading/trailing whitespace."""
        from core.tui.tag_renderer import collapse_system_tags

        content = "  <system-reminder>context</system-reminder>  text  "
        result = collapse_system_tags(content)
        assert result == "text"

    def test_empty_after_removal(self):
        """If only system-reminder content, result should be empty."""
        from core.tui.tag_renderer import collapse_system_tags

        content = "  <system-reminder>only this</system-reminder>  "
        result = collapse_system_tags(content)
        assert result == ""

    def test_multiple_system_reminders(self):
        """Multiple system-reminder tags should all be removed."""
        from core.tui.tag_renderer import collapse_system_tags

        content = "<system-reminder>first</system-reminder>middle<system-reminder>second</system-reminder>end"
        result = collapse_system_tags(content)
        assert result == "middleend"


class TestStripTags:
    """Tests for the strip_tags function."""

    def test_strips_xml_tags_keeps_content(self):
        """XML tags should be stripped but inner content preserved."""
        from core.tui.tag_renderer import strip_tags

        content = "<local-command-caveat>some text</local-command-caveat>"
        result = strip_tags(content)
        assert result == "some text"

    def test_strips_multiple_tags(self):
        """Multiple different tags should all be stripped."""
        from core.tui.tag_renderer import strip_tags

        content = "<system-reminder>context</system-reminder>Hello <command-name>/test</command-name>"
        result = strip_tags(content)
        assert result == "contextHello /test"

    def test_strips_self_closing_tags(self):
        """Self-closing tags should be stripped."""
        from core.tui.tag_renderer import strip_tags

        content = "before <br/> after"
        result = strip_tags(content)
        assert result == "before  after"

    def test_empty_content_returns_empty(self):
        """Empty content should return empty string."""
        from core.tui.tag_renderer import strip_tags

        assert strip_tags("") == ""

    def test_none_returns_none(self):
        """None content should return None (falsy check)."""
        from core.tui.tag_renderer import strip_tags

        # strip_tags checks `if not content` which is True for None
        assert strip_tags(None) is None

    def test_content_without_tags_unchanged(self):
        """Content without tags should pass through unchanged."""
        from core.tui.tag_renderer import strip_tags

        content = "Just plain text with no tags"
        result = strip_tags(content)
        assert result == content

    def test_nested_tags_stripped(self):
        """Nested tags should both be stripped."""
        from core.tui.tag_renderer import strip_tags

        content = "<outer><inner>text</inner></outer>"
        result = strip_tags(content)
        assert result == "text"

    def test_typical_session_topic(self):
        """Typical session topic with system tags should be cleaned."""
        from core.tui.tag_renderer import strip_tags

        content = "<system-reminder>Hook context here</system-reminder>Implement the feature"
        result = strip_tags(content)
        assert result == "Hook context hereImplement the feature"
