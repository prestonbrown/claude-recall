package main

import (
	"bytes"
	"testing"
)

// Help belongs on stdout when it was asked for and on stderr when it is part of
// an error. Hooks capture the CLI's stdout and feed it to a JSON parser, so
// spilling 2.8KB of usage text there on a failure path corrupts the payload -
// the failure mode [L010] describes.
func newHelpTestApp() (*App, *bytes.Buffer, *bytes.Buffer) {
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	return &App{stdout: stdout, stderr: stderr}, stdout, stderr
}

func TestHelp_ExplicitRequestGoesToStdout(t *testing.T) {
	for _, arg := range []string{"help", "--help", "-h"} {
		app, stdout, stderr := newHelpTestApp()

		if code := app.Run([]string{"recall", arg}); code != 0 {
			t.Errorf("%q should exit 0, got %d", arg, code)
		}
		if stdout.Len() == 0 {
			t.Errorf("%q should print help to stdout", arg)
		}
		if stderr.Len() != 0 {
			t.Errorf("%q should leave stderr clean, got: %s", arg, stderr.String())
		}
	}
}

func TestHelp_UnknownCommandKeepsStdoutClean(t *testing.T) {
	app, stdout, stderr := newHelpTestApp()

	code := app.Run([]string{"recall", "search", "foo"})

	if code == 0 {
		t.Error("an unknown command must exit non-zero")
	}
	if stdout.Len() != 0 {
		t.Errorf("an unknown command must not write to stdout, got %d bytes:\n%s",
			stdout.Len(), stdout.String())
	}
	if stderr.Len() == 0 {
		t.Error("an unknown command should explain itself on stderr")
	}
}

func TestHelp_NoArgsKeepsStdoutClean(t *testing.T) {
	app, stdout, stderr := newHelpTestApp()

	code := app.Run([]string{"recall"})

	if code == 0 {
		t.Error("no arguments must exit non-zero")
	}
	if stdout.Len() != 0 {
		t.Errorf("no arguments must not write to stdout, got:\n%s", stdout.String())
	}
	if stderr.Len() == 0 {
		t.Error("no arguments should print usage to stderr")
	}
}
