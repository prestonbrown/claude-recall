#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Transform XML-like tags in content to Rich markup for TUI display."""

import re
from typing import Optional


def render_tags(content: Optional[str]) -> Optional[str]:
    """Transform XML-like tags to Rich markup for display.

    Transformations:
    - <system-reminder>...</system-reminder> -> [dim][System context][/dim]
    - <local-command-caveat>...</local-command-caveat> -> [dim][Command context][/dim]
    - <command-name>NAME</command-name> -> [bold magenta]/NAME[/bold magenta]
    - <tool_use_error>MSG</tool_use_error> -> [red]Error: MSG[/red]
    - Other tags -> strip (keep content)

    Args:
        content: Raw content string potentially containing XML tags

    Returns:
        Content with tags transformed to Rich markup, or None if input is None
    """
    if content is None:
        return None

    if not content:
        return content

    # Transform <system-reminder>...</system-reminder> -> collapsed indicator
    content = re.sub(
        r"<system-reminder>.*?</system-reminder>",
        "[dim][System context][/dim]",
        content,
        flags=re.DOTALL,
    )

    # Transform <local-command-caveat>...</local-command-caveat> -> collapse
    content = re.sub(
        r"<local-command-caveat>.*?</local-command-caveat>",
        "[dim][Command context][/dim]",
        content,
        flags=re.DOTALL,
    )

    # Transform <command-name>NAME</command-name> -> /NAME
    # Handle both <command-name>name</command-name> and <command-name>/name</command-name>
    # Use .*? instead of [^<]+ to handle content containing < characters
    content = re.sub(
        r"<command-name>/?(.*?)</command-name>",
        r"[bold magenta]/\1[/bold magenta]",
        content,
        flags=re.DOTALL,
    )

    # Transform <tool_use_error>MSG</tool_use_error> -> Error: MSG
    # Use .*? instead of [^<]+ to handle error messages containing < characters
    content = re.sub(
        r"<tool_use_error>(.*?)</tool_use_error>",
        r"[red]Error: \1[/red]",
        content,
        flags=re.DOTALL,
    )

    # Strip any remaining unknown tags (but keep content)
    content = re.sub(r"<[^>]+>", "", content)

    return content


def collapse_system_tags(content: str) -> str:
    """Collapse system tags to minimal indicator, keeping other content.

    Useful for preview/summary displays where space is limited.
    Unlike render_tags, this completely removes system-reminder tags
    (no placeholder text).

    Args:
        content: Raw content string potentially containing XML tags

    Returns:
        Content with system-reminder tags removed and result stripped
    """
    # Collapse system-reminder completely (including trailing whitespace)
    content = re.sub(
        r"<system-reminder>.*?</system-reminder>\s*",
        "",
        content,
        flags=re.DOTALL,
    )
    return content.strip()


def strip_tags(content: str) -> str:
    """Remove all XML-like tags from content, keeping inner text.

    Useful for DataTable columns and other displays that don't support
    Rich markup and have limited space.
    """
    if not content:
        return content
    return re.sub(r"<[^>]+>", "", content)
