// Package anthropic provides Claude API integration for relevance scoring
package anthropic

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

const (
	// DefaultTimeout for API calls
	DefaultTimeout = 30 * time.Second

	// HaikuModel is the model used for scoring
	HaikuModel = "claude-3-5-haiku-latest"

	// DefaultMaxTokens for API responses
	DefaultMaxTokens = 1024
)

// Client wraps the Anthropic API
type Client struct {
	apiKey     string
	httpClient *http.Client
	baseURL    string
}

// NewClient creates a new Anthropic client
func NewClient() (*Client, error) {
	apiKey := os.Getenv("ANTHROPIC_API_KEY")
	if apiKey == "" {
		return nil, fmt.Errorf("ANTHROPIC_API_KEY environment variable not set")
	}

	return &Client{
		apiKey: apiKey,
		httpClient: &http.Client{
			Timeout: DefaultTimeout,
		},
		baseURL: "https://api.anthropic.com/v1",
	}, nil
}

// Message represents a chat message
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// MessagesRequest represents a request to the Messages API
type MessagesRequest struct {
	Model     string    `json:"model"`
	MaxTokens int       `json:"max_tokens"`
	Messages  []Message `json:"messages"`
}

// ContentBlock represents a content block in the response
type ContentBlock struct {
	Type string `json:"type"`
	Text string `json:"text,omitempty"`
}

// MessagesResponse represents a response from the Messages API
type MessagesResponse struct {
	ID           string         `json:"id"`
	Type         string         `json:"type"`
	Role         string         `json:"role"`
	Content      []ContentBlock `json:"content"`
	Model        string         `json:"model"`
	StopReason   string         `json:"stop_reason"`
	StopSequence string         `json:"stop_sequence,omitempty"`
	Usage        struct {
		InputTokens  int `json:"input_tokens"`
		OutputTokens int `json:"output_tokens"`
	} `json:"usage"`
}

// ErrorResponse represents an API error
type ErrorResponse struct {
	Type  string `json:"type"`
	Error struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	} `json:"error"`
}

// Complete sends a completion request to the API
func (c *Client) Complete(prompt string) (string, error) {
	return c.CompleteWithTimeout(prompt, DefaultTimeout)
}

// CompleteWithTimeout sends a completion request with a custom timeout
func (c *Client) CompleteWithTimeout(prompt string, timeout time.Duration) (string, error) {
	// Create a client with the specified timeout
	client := &http.Client{Timeout: timeout}

	req := MessagesRequest{
		Model:     HaikuModel,
		MaxTokens: DefaultMaxTokens,
		Messages: []Message{
			{Role: "user", Content: prompt},
		},
	}

	reqBody, err := json.Marshal(req)
	if err != nil {
		return "", fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq, err := http.NewRequest("POST", c.baseURL+"/messages", bytes.NewReader(reqBody))
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}

	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("x-api-key", c.apiKey)
	httpReq.Header.Set("anthropic-version", "2023-06-01")

	resp, err := client.Do(httpReq)
	if err != nil {
		return "", fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		var errResp ErrorResponse
		if err := json.NewDecoder(resp.Body).Decode(&errResp); err == nil {
			return "", fmt.Errorf("API error: %s", errResp.Error.Message)
		}
		return "", fmt.Errorf("API error: status %d", resp.StatusCode)
	}

	var msgResp MessagesResponse
	if err := json.NewDecoder(resp.Body).Decode(&msgResp); err != nil {
		return "", fmt.Errorf("failed to decode response: %w", err)
	}

	// Extract text content
	var result string
	for _, block := range msgResp.Content {
		if block.Type == "text" {
			result += block.Text
		}
	}

	return result, nil
}
