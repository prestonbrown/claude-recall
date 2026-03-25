---
description: Show lesson injection/citation statistics and precision metrics
argument-hint: "[L###] [--weekly]"
---

# Recall Stats

Show how well lessons are being targeted — which get cited vs which are noise.

## Usage

- `/recall stats` — This session's injection/citation breakdown
- `/recall stats L059` — Lesson-specific precision, triggering queries, trigger suggestions
- `/recall stats --weekly` — Week-over-week trend report

## How It Works

The system logs every injection and citation event. Stats computes precision (citations / injections) to identify which lessons are well-targeted and which are noise.

## Commands

| Input | Action |
|-------|--------|
| `/recall stats` | `recall stats` — session summary |
| `/recall stats L059` | `recall stats L059` — lesson detail |
| `/recall stats --weekly` | `recall stats --weekly` — trend report |
