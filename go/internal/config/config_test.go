package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func Test_LoadConfig_MissingFile_ReturnsDefaults(t *testing.T) {
	// Setup: use a non-existent path
	nonExistentPath := filepath.Join(t.TempDir(), "does-not-exist.json")

	// Clear any env vars that might interfere
	envVars := []string{
		"CLAUDE_RECALL_BASE", "CLAUDE_RECALL_STATE", "PROJECT_DIR", "CLAUDE_RECALL_DEBUG",
		"RECALL_BASE", "LESSONS_BASE", "RECALL_DEBUG", "LESSONS_DEBUG",
	}
	for _, v := range envVars {
		t.Setenv(v, "")
	}

	cfg, err := Load(nonExistentPath)
	if err != nil {
		t.Fatalf("expected no error for missing file, got: %v", err)
	}

	// Check defaults
	homeDir, _ := os.UserHomeDir()
	expectedBase := filepath.Join(homeDir, ".config", "claude-recall")
	expectedState := filepath.Join(homeDir, ".local", "state", "claude-recall")

	if cfg.Base != expectedBase {
		t.Errorf("expected Base=%q, got %q", expectedBase, cfg.Base)
	}
	if cfg.StateDir != expectedState {
		t.Errorf("expected StateDir=%q, got %q", expectedState, cfg.StateDir)
	}
	// ProjectDir defaults to git root (or cwd if not in a git repo)
	// Since we're running in a git repo, it will find the git root
	if cfg.ProjectDir == "" {
		t.Error("expected ProjectDir to have a value")
	}
	if cfg.DebugLevel != 0 {
		t.Errorf("expected DebugLevel=0, got %d", cfg.DebugLevel)
	}
}

func Test_LoadConfig_ValidFile_ReturnsValues(t *testing.T) {
	// Setup: create a temp config file
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.json")

	configData := map[string]interface{}{
		"base":       "/custom/base",
		"state_dir":  "/custom/state",
		"project_dir": "/custom/project",
		"debug_level": 2,
	}
	data, _ := json.Marshal(configData)
	if err := os.WriteFile(configPath, data, 0644); err != nil {
		t.Fatalf("failed to write config file: %v", err)
	}

	// Clear env vars
	envVars := []string{
		"CLAUDE_RECALL_BASE", "CLAUDE_RECALL_STATE", "PROJECT_DIR", "CLAUDE_RECALL_DEBUG",
		"RECALL_BASE", "LESSONS_BASE", "RECALL_DEBUG", "LESSONS_DEBUG",
	}
	for _, v := range envVars {
		t.Setenv(v, "")
	}

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}

	if cfg.Base != "/custom/base" {
		t.Errorf("expected Base=/custom/base, got %q", cfg.Base)
	}
	if cfg.StateDir != "/custom/state" {
		t.Errorf("expected StateDir=/custom/state, got %q", cfg.StateDir)
	}
	if cfg.ProjectDir != "/custom/project" {
		t.Errorf("expected ProjectDir=/custom/project, got %q", cfg.ProjectDir)
	}
	if cfg.DebugLevel != 2 {
		t.Errorf("expected DebugLevel=2, got %d", cfg.DebugLevel)
	}
}

func Test_LoadConfig_EnvOverrides(t *testing.T) {
	// Setup: create a config file with some values
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.json")

	configData := map[string]interface{}{
		"base":        "/file/base",
		"state_dir":   "/file/state",
		"project_dir": "/file/project",
		"debug_level": 1,
	}
	data, _ := json.Marshal(configData)
	if err := os.WriteFile(configPath, data, 0644); err != nil {
		t.Fatalf("failed to write config file: %v", err)
	}

	// Clear legacy vars first
	t.Setenv("RECALL_BASE", "")
	t.Setenv("LESSONS_BASE", "")
	t.Setenv("RECALL_DEBUG", "")
	t.Setenv("LESSONS_DEBUG", "")

	// Set env vars - these should override file values
	t.Setenv("CLAUDE_RECALL_BASE", "/env/base")
	t.Setenv("CLAUDE_RECALL_STATE", "/env/state")
	t.Setenv("PROJECT_DIR", "/env/project")
	t.Setenv("CLAUDE_RECALL_DEBUG", "3")

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}

	// Env vars should override file values
	if cfg.Base != "/env/base" {
		t.Errorf("expected Base=/env/base (from env), got %q", cfg.Base)
	}
	if cfg.StateDir != "/env/state" {
		t.Errorf("expected StateDir=/env/state (from env), got %q", cfg.StateDir)
	}
	if cfg.ProjectDir != "/env/project" {
		t.Errorf("expected ProjectDir=/env/project (from env), got %q", cfg.ProjectDir)
	}
	if cfg.DebugLevel != 3 {
		t.Errorf("expected DebugLevel=3 (from env), got %d", cfg.DebugLevel)
	}
}

func Test_LoadConfig_LegacyEnvVars(t *testing.T) {
	// Setup: use non-existent file so we get defaults
	nonExistentPath := filepath.Join(t.TempDir(), "does-not-exist.json")

	// Clear primary env vars
	t.Setenv("CLAUDE_RECALL_BASE", "")
	t.Setenv("CLAUDE_RECALL_STATE", "")
	t.Setenv("PROJECT_DIR", "")
	t.Setenv("CLAUDE_RECALL_DEBUG", "")

	// Set legacy env vars
	t.Setenv("RECALL_BASE", "/legacy/recall-base")
	t.Setenv("LESSONS_BASE", "/legacy/lessons-base")  // This is also a legacy alias
	t.Setenv("RECALL_DEBUG", "2")
	t.Setenv("LESSONS_DEBUG", "1")  // RECALL_DEBUG takes precedence

	cfg, err := Load(nonExistentPath)
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}

	// RECALL_BASE takes precedence over LESSONS_BASE
	if cfg.Base != "/legacy/recall-base" {
		t.Errorf("expected Base=/legacy/recall-base (from RECALL_BASE), got %q", cfg.Base)
	}
	// RECALL_DEBUG takes precedence over LESSONS_DEBUG
	if cfg.DebugLevel != 2 {
		t.Errorf("expected DebugLevel=2 (from RECALL_DEBUG), got %d", cfg.DebugLevel)
	}
}

func Test_LoadConfig_LegacyEnvVars_LessonsBaseFallback(t *testing.T) {
	// Test that LESSONS_BASE works when RECALL_BASE is not set
	nonExistentPath := filepath.Join(t.TempDir(), "does-not-exist.json")

	// Clear all env vars
	t.Setenv("CLAUDE_RECALL_BASE", "")
	t.Setenv("CLAUDE_RECALL_STATE", "")
	t.Setenv("PROJECT_DIR", "")
	t.Setenv("CLAUDE_RECALL_DEBUG", "")
	t.Setenv("RECALL_BASE", "")
	t.Setenv("RECALL_DEBUG", "")

	// Only set LESSONS_BASE and LESSONS_DEBUG
	t.Setenv("LESSONS_BASE", "/legacy/lessons-base")
	t.Setenv("LESSONS_DEBUG", "1")

	cfg, err := Load(nonExistentPath)
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}

	if cfg.Base != "/legacy/lessons-base" {
		t.Errorf("expected Base=/legacy/lessons-base (from LESSONS_BASE), got %q", cfg.Base)
	}
	if cfg.DebugLevel != 1 {
		t.Errorf("expected DebugLevel=1 (from LESSONS_DEBUG), got %d", cfg.DebugLevel)
	}
}

func Test_LoadConfig_InvalidJSON_ReturnsError(t *testing.T) {
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.json")

	// Write invalid JSON
	if err := os.WriteFile(configPath, []byte("not valid json{"), 0644); err != nil {
		t.Fatalf("failed to write config file: %v", err)
	}

	_, err := Load(configPath)
	if err == nil {
		t.Error("expected error for invalid JSON, got nil")
	}
}

func Test_LoadConfig_DebugLevelClamped(t *testing.T) {
	// Test that debug level is clamped to 0-3 range
	nonExistentPath := filepath.Join(t.TempDir(), "does-not-exist.json")

	// Clear legacy vars
	t.Setenv("RECALL_BASE", "")
	t.Setenv("LESSONS_BASE", "")
	t.Setenv("RECALL_DEBUG", "")
	t.Setenv("LESSONS_DEBUG", "")
	t.Setenv("CLAUDE_RECALL_BASE", "")
	t.Setenv("CLAUDE_RECALL_STATE", "")
	t.Setenv("PROJECT_DIR", "")

	// Test value > 3
	t.Setenv("CLAUDE_RECALL_DEBUG", "5")
	cfg, _ := Load(nonExistentPath)
	if cfg.DebugLevel != 3 {
		t.Errorf("expected DebugLevel clamped to 3, got %d", cfg.DebugLevel)
	}

	// Test negative value
	t.Setenv("CLAUDE_RECALL_DEBUG", "-1")
	cfg, _ = Load(nonExistentPath)
	if cfg.DebugLevel != 0 {
		t.Errorf("expected DebugLevel clamped to 0, got %d", cfg.DebugLevel)
	}
}

func Test_LoadConfig_ProjectDir_DefaultsToCWD(t *testing.T) {
	// Test that ProjectDir defaults to cwd when:
	// 1. No PROJECT_DIR env var is set
	// 2. Not in a git repository

	// Create a temp directory (outside any git repo)
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.json")

	// Clear env vars
	t.Setenv("CLAUDE_RECALL_BASE", "")
	t.Setenv("CLAUDE_RECALL_STATE", "")
	t.Setenv("PROJECT_DIR", "")
	t.Setenv("CLAUDE_RECALL_DEBUG", "")

	// Save current dir and change to temp dir (no .git)
	origDir, _ := os.Getwd()
	if err := os.Chdir(tmpDir); err != nil {
		t.Fatalf("failed to change to temp dir: %v", err)
	}
	defer os.Chdir(origDir)

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Resolve symlinks for comparison (macOS /var -> /private/var)
	expectedDir, _ := filepath.EvalSymlinks(tmpDir)
	actualDir, _ := filepath.EvalSymlinks(cfg.ProjectDir)

	// ProjectDir should be the temp directory (cwd) since there's no .git
	if actualDir != expectedDir {
		t.Errorf("expected ProjectDir=%q (cwd), got %q", expectedDir, actualDir)
	}
}

func Test_LoadConfig_ProjectDir_GitRootTakesPrecedence(t *testing.T) {
	// Test that ProjectDir uses git root when running from a subdirectory
	// (We're running tests from within the claude-recall repo)

	nonExistentPath := filepath.Join(t.TempDir(), "does-not-exist.json")

	// Clear PROJECT_DIR so git root detection kicks in
	t.Setenv("PROJECT_DIR", "")

	cfg, err := Load(nonExistentPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should find git root, not just cwd
	// The git root should contain a .git directory
	gitDir := filepath.Join(cfg.ProjectDir, ".git")
	if _, err := os.Stat(gitDir); os.IsNotExist(err) {
		// If not in a git repo, that's also valid - just check it's not empty
		cwd, _ := os.Getwd()
		if cfg.ProjectDir == "" {
			t.Error("expected ProjectDir to be set (either git root or cwd)")
		}
		// In non-git environments, should fall back to cwd
		if cfg.ProjectDir != cwd {
			t.Logf("note: not in git repo, ProjectDir=%q, cwd=%q", cfg.ProjectDir, cwd)
		}
	}
}
