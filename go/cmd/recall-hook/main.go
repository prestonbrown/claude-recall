// Package main provides the recall-hook binary for fast Claude Code hook execution.
package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: recall-hook <command> [args...]")
		os.Exit(1)
	}

	cmd := os.Args[1]
	switch cmd {
	case "stop":
		os.Exit(runStop())
	case "inject":
		os.Exit(runInject())
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", cmd)
		os.Exit(1)
	}
}

// runStop is implemented in stop.go

func runInject() int {
	// TODO: Implement inject hook
	return 0
}
