"""Pure helpers shared by the Windows and Mac layers (no system calls, so the self-test runs them anywhere)."""
import time


def restore_budget(delay, queued=0, chars=0):
    """Longest wait before the old clipboard goes back: the app's usual delay, plus time to work through any
    queued key presses and to take in a long paste."""
    return delay + min(15.0, 0.01 * queued + 0.0005 * chars)


def restore_when_pasted(saved, seq, text, delay, budget, sequence, restore, check=None, sleep=time.sleep,
                        clock=time.monotonic):
    """Put the old clipboard back only after the app has pasted. An app reads the clipboard when it gets round
    to the paste keys, and a long dictation can keep it busy: restoring before that pasted the user's old copy
    instead of their words. Watches the box for the pasted text; if the box can't be read, waits the full
    budget. Never restores sooner than the app's usual delay, or if something else was copied meanwhile.
    sequence() -> the clipboard's change counter; restore(saved) puts the old clipboard back."""
    if check is None:
        from .. import instant
        check = instant.pasted
    start = clock()
    seen = None
    while clock() - start < budget:
        try:
            seen = check(text)
        except Exception:
            seen = None
        if seen is not False:
            break
        sleep(0.05)
    elapsed = clock() - start
    sleep(max(0.0, (delay if seen else budget) - elapsed))
    if sequence() == seq:  # "Clipboard changed since paste, skipping restoration"
        restore(saved)
        return True
    return False


def utf16_slice(text, start, end=None):
    """text[start:end] counted in UTF-16 units, the way macOS Accessibility and Windows count characters."""
    raw = text.encode("utf-16-le")
    part = raw[start * 2:None if end is None else end * 2]
    return part.decode("utf-16-le", errors="ignore")


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2
