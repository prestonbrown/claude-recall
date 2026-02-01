// Package config handles configuration loading for claude-recall.
// It supports JSON config files, environment variables, and sensible defaults.
package config

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
)

// Config holds the configuration for claude-recall.
type Config struct {
	Base       string `json:"base"`        // Code directory, default: ~/.config/claude-recall
	StateDir   string `json:"state_dir"`   // State directory, default: ~/.local/state/claude-recall
	ProjectDir string `json:"project_dir"` // Project root, default: git root or cwd
	DebugLevel int    `json:"debug_level"` // Debug level 0-3, from CLAUDE_RECALL_DEBUG
}

// Load reads configuration from the given JSON file path,
// applies defaults for missing values, and overrides with environment variables.
func Load(configPath string) (*Config, error) {
	cfg := &Config{}

	// Try to read config file
	if data, err := os.ReadFile(configPath); err == nil {
		if err := json.Unmarshal(data, cfg); err != nil {
			return nil, err
		}
	}
	// If file doesn't exist, that's fine - we'll use defaults

	// Apply defaults for any empty values
	applyDefaults(cfg)

	// Override with environment variables (env vars take highest precedence)
	applyEnvOverrides(cfg)

	// Clamp debug level to valid range
	if cfg.DebugLevel < 0 {
		cfg.DebugLevel = 0
	}
	if cfg.DebugLevel > 3 {
		cfg.DebugLevel = 3
	}

	return cfg, nil
}

// applyDefaults sets default values for any empty config fields.
func applyDefaults(cfg *Config) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		homeDir = ""
	}

	if cfg.Base == "" {
		cfg.Base = filepath.Join(homeDir, ".config", "claude-recall")
	}
	if cfg.StateDir == "" {
		cfg.StateDir = filepath.Join(homeDir, ".local", "state", "claude-recall")
	}
	if cfg.ProjectDir == "" {
		cfg.ProjectDir = findProjectDir()
	}
}

// applyEnvOverrides overrides config values with environment variables.
// Priority: CLAUDE_RECALL_* > RECALL_* > LESSONS_*
func applyEnvOverrides(cfg *Config) {
	// Base directory: CLAUDE_RECALL_BASE > RECALL_BASE > LESSONS_BASE
	if val := os.Getenv("CLAUDE_RECALL_BASE"); val != "" {
		cfg.Base = val
	} else if val := os.Getenv("RECALL_BASE"); val != "" {
		cfg.Base = val
	} else if val := os.Getenv("LESSONS_BASE"); val != "" {
		cfg.Base = val
	}

	// State directory: CLAUDE_RECALL_STATE
	if val := os.Getenv("CLAUDE_RECALL_STATE"); val != "" {
		cfg.StateDir = val
	}

	// Project directory: PROJECT_DIR
	if val := os.Getenv("PROJECT_DIR"); val != "" {
		cfg.ProjectDir = val
	}

	// Debug level: CLAUDE_RECALL_DEBUG > RECALL_DEBUG > LESSONS_DEBUG
	if val := os.Getenv("CLAUDE_RECALL_DEBUG"); val != "" {
		if level, err := strconv.Atoi(val); err == nil {
			cfg.DebugLevel = level
		}
	} else if val := os.Getenv("RECALL_DEBUG"); val != "" {
		if level, err := strconv.Atoi(val); err == nil {
			cfg.DebugLevel = level
		}
	} else if val := os.Getenv("LESSONS_DEBUG"); val != "" {
		if level, err := strconv.Atoi(val); err == nil {
			cfg.DebugLevel = level
		}
	}
}

// findProjectDir attempts to find the git root, falling back to cwd.
func findProjectDir() string {
	// Try to get git root
	cmd := exec.Command("git", "rev-parse", "--show-toplevel")
	output, err := cmd.Output()
	if err == nil {
		return strings.TrimSpace(string(output))
	}

	// Fall back to current working directory
	cwd, err := os.Getwd()
	if err != nil {
		return ""
	}
	return cwd
}
