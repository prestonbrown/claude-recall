package lock

import (
	"os"
	"sync"
	"syscall"
)

// FileLock represents a file lock for safe concurrent access
type FileLock struct {
	path     string
	file     *os.File
	released bool
	mu       sync.Mutex
}

// Acquire obtains an exclusive lock on the file. Blocks until lock available.
func Acquire(path string) (*FileLock, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return nil, err
	}

	// Block until lock acquired (LOCK_EX = exclusive lock)
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX); err != nil {
		file.Close()
		return nil, err
	}

	return &FileLock{
		path: path,
		file: file,
	}, nil
}

// TryAcquire attempts to obtain a lock without blocking. Returns nil if unavailable.
func TryAcquire(path string) (*FileLock, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return nil, err
	}

	// Try to acquire lock without blocking (LOCK_NB = non-blocking)
	err = syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if err != nil {
		file.Close()
		// EWOULDBLOCK means lock is held by another process
		if err == syscall.EWOULDBLOCK {
			return nil, nil
		}
		return nil, err
	}

	return &FileLock{
		path: path,
		file: file,
	}, nil
}

// Release releases the lock and closes the file
func (l *FileLock) Release() error {
	l.mu.Lock()
	defer l.mu.Unlock()

	if l.released {
		return nil
	}

	l.released = true

	// Unlock the file
	if err := syscall.Flock(int(l.file.Fd()), syscall.LOCK_UN); err != nil {
		l.file.Close()
		return err
	}

	return l.file.Close()
}
