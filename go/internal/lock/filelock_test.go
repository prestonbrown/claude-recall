package lock

import (
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func Test_Acquire_CreatesLockFile(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "test.lock")

	// Verify lock file doesn't exist
	if _, err := os.Stat(lockPath); !os.IsNotExist(err) {
		t.Fatal("lock file should not exist before acquire")
	}

	lock, err := Acquire(lockPath)
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	defer lock.Release()

	// Verify lock file now exists
	if _, err := os.Stat(lockPath); err != nil {
		t.Fatalf("lock file should exist after acquire: %v", err)
	}
}

func Test_Acquire_Blocking(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "test.lock")

	// First goroutine acquires lock
	lock1, err := Acquire(lockPath)
	if err != nil {
		t.Fatalf("first Acquire failed: %v", err)
	}

	acquired := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)

	// Second goroutine tries to acquire - should block
	go func() {
		defer wg.Done()
		lock2, err := Acquire(lockPath)
		if err != nil {
			t.Errorf("second Acquire failed: %v", err)
			return
		}
		close(acquired)
		lock2.Release()
	}()

	// Give second goroutine time to attempt acquire
	time.Sleep(50 * time.Millisecond)

	// Verify second acquire is still blocked
	select {
	case <-acquired:
		t.Fatal("second acquire should be blocked while first holds lock")
	default:
		// Expected - second acquire is blocked
	}

	// Release first lock
	lock1.Release()

	// Wait for second to acquire (with timeout)
	select {
	case <-acquired:
		// Expected - second acquired after first released
	case <-time.After(1 * time.Second):
		t.Fatal("second acquire should succeed after first release")
	}

	wg.Wait()
}

func Test_TryAcquire_ReturnsNil(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "test.lock")

	// First acquire
	lock1, err := Acquire(lockPath)
	if err != nil {
		t.Fatalf("first Acquire failed: %v", err)
	}
	defer lock1.Release()

	// TryAcquire should return nil without blocking
	lock2, err := TryAcquire(lockPath)
	if err != nil {
		t.Fatalf("TryAcquire returned error: %v", err)
	}
	if lock2 != nil {
		lock2.Release()
		t.Fatal("TryAcquire should return nil when lock is held")
	}
}

func Test_TryAcquire_Succeeds_WhenFree(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "test.lock")

	// TryAcquire on free lock should succeed
	lock, err := TryAcquire(lockPath)
	if err != nil {
		t.Fatalf("TryAcquire failed: %v", err)
	}
	if lock == nil {
		t.Fatal("TryAcquire should return non-nil lock when free")
	}
	defer lock.Release()
}

func Test_Release_FreesLock(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "test.lock")

	// Acquire and release
	lock1, err := Acquire(lockPath)
	if err != nil {
		t.Fatalf("first Acquire failed: %v", err)
	}
	if err := lock1.Release(); err != nil {
		t.Fatalf("Release failed: %v", err)
	}

	// Should be able to acquire again immediately
	lock2, err := TryAcquire(lockPath)
	if err != nil {
		t.Fatalf("TryAcquire after release failed: %v", err)
	}
	if lock2 == nil {
		t.Fatal("should be able to acquire lock after release")
	}
	defer lock2.Release()
}

func Test_Release_Idempotent(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "test.lock")

	lock, err := Acquire(lockPath)
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	// First release should succeed
	err = lock.Release()
	if err != nil {
		t.Fatalf("first Release failed: %v", err)
	}

	// Second release should also be safe (no panic, no error)
	err = lock.Release()
	if err != nil {
		t.Fatalf("second Release should be safe: %v", err)
	}
}
