package sessionfiles

import (
	"path/filepath"
	"strings"
)

const maxSegments = 20

var commonPrefixes = map[string]bool{
	".": true, "home": true, "users": true, "tmp": true, "var": true,
}

var knownExtensions = map[string]bool{
	"go": true, "py": true, "js": true, "ts": true, "tsx": true, "jsx": true,
	"c": true, "h": true, "cpp": true, "rs": true, "rb": true, "java": true,
	"sh": true, "bash": true, "zsh": true, "md": true, "txt": true, "json": true,
	"yaml": true, "yml": true, "toml": true, "xml": true, "html": true, "css": true,
	"sql": true, "proto": true, "lua": true, "zig": true, "swift": true,
}

func ExtractSegments(paths []string, projectRoot string) []string {
	if len(paths) == 0 {
		return nil
	}
	root := strings.TrimSuffix(projectRoot, "/") + "/"
	seen := make(map[string]bool)
	var segments []string

	for _, p := range paths {
		rel := p
		if strings.HasPrefix(p, root) {
			rel = strings.TrimPrefix(p, root)
		}
		parts := strings.Split(rel, "/")
		for _, part := range parts {
			if part == "" {
				continue
			}
			ext := filepath.Ext(part)
			if ext != "" && knownExtensions[ext[1:]] {
				part = strings.TrimSuffix(part, ext)
			}
			if len(part) < 2 || commonPrefixes[part] || seen[part] {
				continue
			}
			seen[part] = true
			segments = append(segments, part)
			if len(segments) >= maxSegments {
				return segments
			}
		}
	}
	return segments
}
