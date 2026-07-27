// Package main provides the recall CLI for managing lessons.
package main

import (
	"os"
)

func main() {
	app := NewApp()
	os.Exit(app.Run(os.Args))
}
