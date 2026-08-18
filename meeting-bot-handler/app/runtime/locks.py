"""
Concurrency primitives for Bot session operations.

Used to prevent races such as:
- start_recording + start_recording
- leave + start_recording
- stop + leave
"""
