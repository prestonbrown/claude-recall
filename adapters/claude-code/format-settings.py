#!/usr/bin/env python3
"""Format config.json to match the user's preferred style."""
import json
import sys


def format_hook(h, indent=8):
    """Format a single hook object on one line."""
    parts = [f'"{k}": {json.dumps(v)}' for k, v in h.items()]
    return " " * indent + "{ " + ", ".join(parts) + " }"


def format_hooks_array(hooks, indent=8):
    """Format array of hook objects."""
    return ",\n".join(format_hook(h, indent) for h in hooks)


def format_post_tool_use(entries):
    """Format PostToolUse with matchers."""
    lines = []
    for i, entry in enumerate(entries):
        comma = "," if i < len(entries) - 1 else ""
        lines.append("      {")
        lines.append(f'        "matcher": {json.dumps(entry["matcher"])},')
        lines.append('        "hooks": [')
        lines.append(format_hooks_array(entry.get("hooks", []), 10))
        lines.append("        ]")
        lines.append("      }" + comma)
    return "\n".join(lines)


def format_settings(data):
    """Format settings JSON to match user's style."""
    output_lines = ["{"]

    # Non-hooks fields first
    non_hooks_keys = [k for k in data.keys() if k != "hooks"]
    has_hooks = "hooks" in data

    for i, key in enumerate(non_hooks_keys):
        value = data[key]
        formatted = json.dumps(value, indent=2).replace("\n", "\n  ")
        # Add comma if there are more non-hooks fields or if hooks section follows
        is_last = (i == len(non_hooks_keys) - 1)
        comma = "," if not is_last or has_hooks else ""
        output_lines.append(f'  "{key}": {formatted}{comma}')
        output_lines.append("")

    # Hooks section
    if "hooks" in data:
        output_lines.append('  "hooks": {')
        hooks = data["hooks"]
        hook_keys = list(hooks.keys())
        for i, key in enumerate(hook_keys):
            comma = "," if i < len(hook_keys) - 1 else ""
            if key == "PostToolUse":
                output_lines.append(f'    "{key}": [')
                output_lines.append(format_post_tool_use(hooks[key]))
                output_lines.append("    ]" + comma)
            else:
                output_lines.append(f'    "{key}": [' + "{")
                for entry in hooks[key]:
                    output_lines.append('      "hooks": [')
                    output_lines.append(format_hooks_array(entry.get("hooks", [])))
                    output_lines.append("      ]")
                output_lines.append("    }]" + comma)
            if i < len(hook_keys) - 1:
                output_lines.append("")
        output_lines.append("  }")

    output_lines.append("}")
    return "\n".join(output_lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: format-settings.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    print(format_settings(data))


if __name__ == "__main__":
    main()
