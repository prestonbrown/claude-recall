// Package main provides the recall CLI for managing lessons and handoffs.
package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: recall <command> [args...]")
		os.Exit(1)
	}

	cmd := os.Args[1]
	switch cmd {
	case "inject":
		os.Exit(runInject())
	case "add":
		os.Exit(runAdd())
	case "cite":
		os.Exit(runCite())
	case "list":
		os.Exit(runList())
	case "handoff":
		os.Exit(runHandoff())
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", cmd)
		os.Exit(1)
	}
}

func runInject() int {
	// TODO: Implement inject command
	return 0
}

func runAdd() int {
	// TODO: Implement add command
	return 0
}

func runCite() int {
	// TODO: Implement cite command
	return 0
}

func runList() int {
	// TODO: Implement list command
	return 0
}

func runHandoff() int {
	// TODO: Implement handoff command
	return 0
}
