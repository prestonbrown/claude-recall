package sessionfiles

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

type sessionFileData struct {
	Paths   []string `json:"paths"`
	Updated string   `json:"updated"`
}

func FilePath(stateDir, sessionID string) string {
	return filepath.Join(stateDir, fmt.Sprintf("session-files-%s.json", sessionID))
}

func Read(path string) ([]string, error) {
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var sf sessionFileData
	if err := json.Unmarshal(data, &sf); err != nil {
		return nil, err
	}
	return sf.Paths, nil
}

func Write(path string, paths []string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	sf := sessionFileData{
		Paths:   paths,
		Updated: time.Now().UTC().Format(time.RFC3339),
	}
	data, err := json.Marshal(sf)
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func Merge(path string, newPaths []string) error {
	existing, err := Read(path)
	if err != nil {
		return err
	}
	seen := make(map[string]bool, len(existing))
	for _, p := range existing {
		seen[p] = true
	}
	for _, p := range newPaths {
		if !seen[p] {
			existing = append(existing, p)
			seen[p] = true
		}
	}
	return Write(path, existing)
}

func Clear(path string) {
	os.Remove(path)
}
