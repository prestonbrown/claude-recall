---
description: Mark an injected lesson as noise for the current context
argument-hint: "<ID>"
---

# Recall Dismiss

Signal that a lesson injection was not relevant to what you're working on.

## Usage

`/recall dismiss L059` — mark L059 as noise for this session

## What It Does

- Logs a dismiss event to the session event log
- Increases the lesson's noise rate in `/recall stats`
- Does NOT remove, hide, or modify the lesson
