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

	EventLogEnabled       *bool `json:"event_log_enabled"`        // Master switch for session-log writing, default: true
	EventLogRetentionDays int   `json:"event_log_retention_days"` // Events older than this pruned during decay, default: 90
	DigestEnabled         *bool `json:"digest_enabled"`           // Whether to auto-generate weekly digests, default: true

	// FeedbackMinInjections/FeedbackMaxCiteRatio/FeedbackPenalty drove the retired
	// binary injection penalty (ShouldPenalize). Still parsed for backward compatibility
	// with existing config.json files, but no longer consulted by the score path.
	FeedbackMinInjections int     `json:"feedbackMinInjections"` // Min injections before penalty eligible, default: 5
	FeedbackMaxCiteRatio  float64 `json:"feedbackMaxCiteRatio"`  // Citation ratio below which penalty applies, default: 0.2
	FeedbackPenalty       float64 `json:"feedbackPenalty"`       // Score multiplier applied to penalized lessons, default: 0.5

	// Trust* parameterize the graduated per-lesson precision multiplier applied in the
	// score path: multiplier = clamp(Trust/prior, TrustFloor, 1.0) once a lesson has at
	// least TrustMinInjections injections, where Trust = (C+TrustAlpha)/(I+TrustAlpha+TrustBeta).
	TrustAlpha         float64 `json:"trustAlpha"`         // Prior citation pseudo-count, default: 1.0
	TrustBeta          float64 `json:"trustBeta"`          // Prior non-citation pseudo-count, default: 1.0
	TrustFloor         float64 `json:"trustFloor"`         // Lowest multiplier a penalized lesson can reach, default: 0.2
	TrustMinInjections int     `json:"trustMinInjections"` // Injections required before the multiplier engages, default: 3
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

// boolPtr returns a pointer to a bool value.
func boolPtr(b bool) *bool { return &b }

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
	if cfg.EventLogEnabled == nil {
		cfg.EventLogEnabled = boolPtr(true)
	}
	if cfg.EventLogRetentionDays == 0 {
		cfg.EventLogRetentionDays = 90
	}
	if cfg.DigestEnabled == nil {
		cfg.DigestEnabled = boolPtr(true)
	}
	if cfg.FeedbackMinInjections == 0 {
		cfg.FeedbackMinInjections = 5
	}
	if cfg.FeedbackMaxCiteRatio == 0 {
		cfg.FeedbackMaxCiteRatio = 0.2
	}
	if cfg.FeedbackPenalty == 0 {
		cfg.FeedbackPenalty = 0.5
	}
	// Zero-sentinel defaulting (the convention used throughout this file): an explicit 0
	// in config.json is indistinguishable from "unset" and is replaced by the default.
	// For TrustFloor and TrustMinInjections, 0 is a semantically meaningful value
	// (full suppression / no warm-up gate) that therefore cannot be set via config today;
	// switch these to pointer fields if that tunability is ever needed.
	if cfg.TrustAlpha == 0 {
		cfg.TrustAlpha = 1.0
	}
	if cfg.TrustBeta == 0 {
		cfg.TrustBeta = 1.0
	}
	if cfg.TrustFloor == 0 {
		cfg.TrustFloor = 0.2
	}
	if cfg.TrustMinInjections == 0 {
		cfg.TrustMinInjections = 3
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

	// Event log enabled: CLAUDE_RECALL_EVENT_LOG_ENABLED
	if val := os.Getenv("CLAUDE_RECALL_EVENT_LOG_ENABLED"); val != "" {
		if b, err := strconv.ParseBool(val); err == nil {
			cfg.EventLogEnabled = boolPtr(b)
		}
	}

	// Event log retention days: CLAUDE_RECALL_EVENT_LOG_RETENTION_DAYS
	if val := os.Getenv("CLAUDE_RECALL_EVENT_LOG_RETENTION_DAYS"); val != "" {
		if days, err := strconv.Atoi(val); err == nil {
			cfg.EventLogRetentionDays = days
		}
	}

	// Digest enabled: CLAUDE_RECALL_DIGEST_ENABLED
	if val := os.Getenv("CLAUDE_RECALL_DIGEST_ENABLED"); val != "" {
		if b, err := strconv.ParseBool(val); err == nil {
			cfg.DigestEnabled = boolPtr(b)
		}
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
