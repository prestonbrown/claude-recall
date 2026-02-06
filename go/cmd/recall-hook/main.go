// Package main provides the recall-hook binary for fast Claude Code hook execution.
package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		printHelp()
		os.Exit(1)
	}

	cmd := os.Args[1]
	switch cmd {
	case "help", "--help", "-h":
		printHelp()
		os.Exit(0)
	case "stop":
		os.Exit(runStop())
	case "inject":
		os.Exit(runInject())
	case "inject-combined":
		os.Exit(runInjectCombined())
	case "stop-hook-batch":
		os.Exit(runStopHookBatch())
	case "stop-all":
		os.Exit(runStopAll())
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", cmd)
		printHelp()
		os.Exit(1)
	}
}

func printHelp() {
	help := `recall-hook - Fast Claude Code hook executor

Usage: recall-hook <command> [args...]

Commands:
  stop                Parse transcript and process citations
                      Input: JSON {"cwd", "session_id", "transcript_path"}
                      Output: JSON {"citations", "citations_processed", "messages_processed"}

  inject [n]          Output top n lessons for context injection
                      Default: 5 lessons

  inject-combined [n] Output lessons, handoffs, and todos as JSON
                      Input: JSON {"cwd", "session_id"} (optional)
                      Output: JSON {"lessons", "handoffs", "todos"}

  stop-hook-batch     Batch process citations, handoffs, and todos
                      Input: JSON from stdin with transcript data
                      Output: JSON results

Options:
  help, --help, -h    Show this help message
`
	fmt.Print(help)
}

// runStop is implemented in stop.go
// runInject is implemented in inject.go
// runInjectCombined is implemented in inject.go
// runStopHookBatch is implemented in batch.go
