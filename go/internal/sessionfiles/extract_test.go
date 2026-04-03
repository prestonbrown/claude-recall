package sessionfiles

import (
	"fmt"
	"testing"
)

func TestExtractSegments_Basic(t *testing.T) {
	paths := []string{"/home/user/project/src/api/handler.go"}
	segments := ExtractSegments(paths, "/home/user/project")
	expected := map[string]bool{"src": true, "api": true, "handler": true}
	for _, s := range segments {
		if !expected[s] {
			t.Errorf("unexpected segment %q", s)
		}
	}
	if len(segments) != len(expected) {
		t.Errorf("expected %d segments, got %d: %v", len(expected), len(segments), segments)
	}
}

func TestExtractSegments_DropsExtensions(t *testing.T) {
	paths := []string{"/proj/src/main.py", "/proj/src/test.go", "/proj/docs/readme.md"}
	segments := ExtractSegments(paths, "/proj")
	for _, s := range segments {
		if s == "py" || s == "go" || s == "md" {
			t.Errorf("should not include extension: %s", s)
		}
	}
}

func TestExtractSegments_DropsCommonPrefixes(t *testing.T) {
	paths := []string{"/home/user/project/src/core.go"}
	segments := ExtractSegments(paths, "/home/user/project")
	for _, s := range segments {
		if s == "home" || s == "user" || s == "project" {
			t.Errorf("should not include common prefix segment: %s", s)
		}
	}
}

func TestExtractSegments_Deduplicates(t *testing.T) {
	paths := []string{"/proj/src/a.go", "/proj/src/b.go", "/proj/src/c.go"}
	segments := ExtractSegments(paths, "/proj")
	srcCount := 0
	for _, s := range segments {
		if s == "src" {
			srcCount++
		}
	}
	if srcCount != 1 {
		t.Errorf("expected 'src' once, got %d times", srcCount)
	}
}

func TestExtractSegments_CapsAt20(t *testing.T) {
	paths := make([]string, 30)
	for i := range paths {
		paths[i] = fmt.Sprintf("/proj/dir%d/file%d.go", i, i)
	}
	segments := ExtractSegments(paths, "/proj")
	if len(segments) > 20 {
		t.Errorf("expected max 20 segments, got %d", len(segments))
	}
}

func TestExtractSegments_EmptyPaths(t *testing.T) {
	segments := ExtractSegments(nil, "/proj")
	if len(segments) != 0 {
		t.Errorf("expected empty segments, got %v", segments)
	}
}

func TestExtractSegments_DropsShortSegments(t *testing.T) {
	paths := []string{"/proj/a/b/src/handler.go"}
	segments := ExtractSegments(paths, "/proj")
	for _, s := range segments {
		if len(s) < 2 {
			t.Errorf("should not include short segment: %q", s)
		}
	}
}
