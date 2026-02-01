package citations

import (
	"reflect"
	"testing"

	"github.com/pbrown/claude-recall/internal/transcript"
)

func Test_Extract_SingleCitation(t *testing.T) {
	text := "As mentioned in [L001], this is important."
	citations := Extract(text)

	if len(citations) != 1 {
		t.Fatalf("expected 1 citation, got %d", len(citations))
	}
	if citations[0].Type != "L" {
		t.Errorf("expected type L, got %s", citations[0].Type)
	}
	if citations[0].ID != "L001" {
		t.Errorf("expected ID L001, got %s", citations[0].ID)
	}
}

func Test_Extract_MultipleCitations(t *testing.T) {
	text := "See [L001] and [S002] for details."
	citations := Extract(text)

	if len(citations) != 2 {
		t.Fatalf("expected 2 citations, got %d", len(citations))
	}

	expected := []Citation{
		{Type: "L", ID: "L001"},
		{Type: "S", ID: "S002"},
	}
	if !reflect.DeepEqual(citations, expected) {
		t.Errorf("expected %v, got %v", expected, citations)
	}
}

func Test_Extract_FilterStarRatings(t *testing.T) {
	text := "Rating: [★★★☆☆] and citation [L001]"
	citations := Extract(text)

	if len(citations) != 1 {
		t.Fatalf("expected 1 citation, got %d", len(citations))
	}
	if citations[0].ID != "L001" {
		t.Errorf("expected ID L001, got %s", citations[0].ID)
	}
}

func Test_Extract_FilterNumericRatings(t *testing.T) {
	text := "Score [3|4] and [10|5] but also [L001]"
	citations := Extract(text)

	if len(citations) != 1 {
		t.Fatalf("expected 1 citation, got %d", len(citations))
	}
	if citations[0].ID != "L001" {
		t.Errorf("expected ID L001, got %s", citations[0].ID)
	}
}

func Test_Extract_Dedupe(t *testing.T) {
	text := "[L001] is cited again [L001] here"
	citations := Extract(text)

	if len(citations) != 1 {
		t.Fatalf("expected 1 citation (deduplicated), got %d", len(citations))
	}
	if citations[0].ID != "L001" {
		t.Errorf("expected ID L001, got %s", citations[0].ID)
	}
}

func Test_Extract_OrderPreserved(t *testing.T) {
	text := "[S003] then [L001] then [H002]"
	citations := Extract(text)

	if len(citations) != 3 {
		t.Fatalf("expected 3 citations, got %d", len(citations))
	}

	expected := []Citation{
		{Type: "S", ID: "S003"},
		{Type: "L", ID: "L001"},
		{Type: "H", ID: "H002"},
	}
	if !reflect.DeepEqual(citations, expected) {
		t.Errorf("expected %v, got %v", expected, citations)
	}
}

func Test_Extract_FilterTemplates(t *testing.T) {
	text := "Template [L###] and real [L001]"
	citations := Extract(text)

	if len(citations) != 1 {
		t.Fatalf("expected 1 citation, got %d", len(citations))
	}
	if citations[0].ID != "L001" {
		t.Errorf("expected ID L001, got %s", citations[0].ID)
	}
}

func Test_ExtractFromMessages(t *testing.T) {
	messages := []transcript.Message{
		{Type: "user", Content: ""},
		{Type: "assistant", Content: "See [L001] for details"},
		{Type: "assistant", Content: "Also [S002] is relevant"},
	}
	citations := ExtractFromMessages(messages)

	if len(citations) != 2 {
		t.Fatalf("expected 2 citations, got %d", len(citations))
	}

	expected := []Citation{
		{Type: "L", ID: "L001"},
		{Type: "S", ID: "S002"},
	}
	if !reflect.DeepEqual(citations, expected) {
		t.Errorf("expected %v, got %v", expected, citations)
	}
}

func Test_Extract_EmptyText(t *testing.T) {
	citations := Extract("")

	if len(citations) != 0 {
		t.Fatalf("expected 0 citations, got %d", len(citations))
	}
}

func Test_Extract_NoCitations(t *testing.T) {
	text := "This text has no citations at all."
	citations := Extract(text)

	if len(citations) != 0 {
		t.Fatalf("expected 0 citations, got %d", len(citations))
	}
}

func Test_Extract_HandoffCitation(t *testing.T) {
	text := "Working on [H001] handoff"
	citations := Extract(text)

	if len(citations) != 1 {
		t.Fatalf("expected 1 citation, got %d", len(citations))
	}
	if citations[0].Type != "H" {
		t.Errorf("expected type H, got %s", citations[0].Type)
	}
	if citations[0].ID != "H001" {
		t.Errorf("expected ID H001, got %s", citations[0].ID)
	}
}

func Test_Extract_MixedContent(t *testing.T) {
	text := `Rating [★★★☆☆] score [3|4] template [L###]
But valid citations: [L001], [S002], [H003]
Duplicate [L001] should not appear twice`

	citations := Extract(text)

	if len(citations) != 3 {
		t.Fatalf("expected 3 citations, got %d", len(citations))
	}

	expected := []Citation{
		{Type: "L", ID: "L001"},
		{Type: "S", ID: "S002"},
		{Type: "H", ID: "H003"},
	}
	if !reflect.DeepEqual(citations, expected) {
		t.Errorf("expected %v, got %v", expected, citations)
	}
}
