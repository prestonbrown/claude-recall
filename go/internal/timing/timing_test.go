package timing

import (
	"testing"
	"time"
)

func Test_Timer_ElapsedMs_Increases(t *testing.T) {
	timer := New()

	elapsed1 := timer.ElapsedMs()
	time.Sleep(10 * time.Millisecond)
	elapsed2 := timer.ElapsedMs()

	if elapsed2 <= elapsed1 {
		t.Errorf("elapsed time should increase: first=%d, second=%d", elapsed1, elapsed2)
	}

	if elapsed2 < 10 {
		t.Errorf("elapsed time should be at least 10ms after sleeping 10ms: got %d", elapsed2)
	}
}

func Test_Timer_Phase_Duration(t *testing.T) {
	timer := New()

	timer.StartPhase("test-phase")
	time.Sleep(15 * time.Millisecond)
	duration := timer.EndPhase("test-phase")

	if duration < 15 {
		t.Errorf("phase duration should be at least 15ms: got %d", duration)
	}

	if duration > 100 {
		t.Errorf("phase duration should be reasonable (< 100ms): got %d", duration)
	}
}

func Test_Timer_Multiple_Phases(t *testing.T) {
	timer := New()

	timer.StartPhase("phase-a")
	time.Sleep(10 * time.Millisecond)
	durationA := timer.EndPhase("phase-a")

	timer.StartPhase("phase-b")
	time.Sleep(20 * time.Millisecond)
	durationB := timer.EndPhase("phase-b")

	if durationA < 10 {
		t.Errorf("phase-a duration should be at least 10ms: got %d", durationA)
	}

	if durationB < 20 {
		t.Errorf("phase-b duration should be at least 20ms: got %d", durationB)
	}

	if durationB <= durationA {
		t.Errorf("phase-b should be longer than phase-a: a=%d, b=%d", durationA, durationB)
	}
}

func Test_Timer_Phases_Map(t *testing.T) {
	timer := New()

	timer.StartPhase("alpha")
	time.Sleep(5 * time.Millisecond)
	timer.EndPhase("alpha")

	timer.StartPhase("beta")
	time.Sleep(10 * time.Millisecond)
	timer.EndPhase("beta")

	phases := timer.Phases()

	if len(phases) != 2 {
		t.Errorf("expected 2 phases, got %d", len(phases))
	}

	if _, ok := phases["alpha"]; !ok {
		t.Error("phases map should contain 'alpha'")
	}

	if _, ok := phases["beta"]; !ok {
		t.Error("phases map should contain 'beta'")
	}

	if phases["alpha"] < 5 {
		t.Errorf("alpha duration should be at least 5ms: got %d", phases["alpha"])
	}

	if phases["beta"] < 10 {
		t.Errorf("beta duration should be at least 10ms: got %d", phases["beta"])
	}
}
