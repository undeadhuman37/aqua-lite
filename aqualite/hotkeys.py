"""Shortcut logic, driven by raw virtual-key codes from a low-level keyboard hook.

Works on VK codes (not characters), so it behaves the same with Arabic, English or any layout.
Pure Python: the Windows hook in winapi.py feeds it, and selftest.py drives it directly.
"""
import time

CTRL, SHIFT, ALT, WIN = {0x11, 0xA2, 0xA3}, {0x10, 0xA0, 0xA1}, {0x12, 0xA4, 0xA5}, {0x5B, 0x5C}
MODIFIER_VKS = CTRL | SHIFT | ALT | WIN

KEY_NAMES = {
    "ctrl": CTRL, "control": CTRL, "lctrl": {0xA2}, "left ctrl": {0xA2}, "rctrl": {0xA3}, "right ctrl": {0xA3},
    "shift": SHIFT, "lshift": {0xA0}, "rshift": {0xA1}, "right shift": {0xA1},
    "alt": ALT, "lalt": {0xA4}, "left alt": {0xA4}, "ralt": {0xA5}, "right alt": {0xA5}, "altgr": {0xA5},
    "win": WIN, "windows": WIN, "lwin": {0x5B}, "rwin": {0x5C},
    "space": {0x20}, "backspace": {0x08}, "esc": {0x1B}, "escape": {0x1B}, "tab": {0x09}, "enter": {0x0D},
    "capslock": {0x14}, "caps lock": {0x14}, "insert": {0x2D}, "delete": {0x2E}, "home": {0x24},
    "end": {0x23}, "pageup": {0x21}, "pagedown": {0x22}, "pause": {0x13}, "scrolllock": {0x91},
    "menu": {0x5D}, "apps": {0x5D}, "`": {0xC0}, "backquote": {0xC0},
    **{f"f{i}": {0x6F + i} for i in range(1, 25)},
    **{chr(c): {c - 32} for c in range(ord("a"), ord("z") + 1)},
    **{str(d): {0x30 + d} for d in range(10)},
}


def parse(spec):
    """'ctrl+win' -> [CTRL, WIN] (a list of VK groups). Raises ValueError on unknown names."""
    groups = []
    for part in (spec or "").lower().split("+"):
        part = part.strip()
        if not part:
            continue
        if part not in KEY_NAMES:
            raise ValueError(f"Unknown key '{part}'")
        groups.append(set(KEY_NAMES[part]))
    if not groups:
        raise ValueError("Empty shortcut")
    return groups


class HotkeyMachine:
    """Calls emit(name, command_mode) with: start, stop, cancel, lock, command, paste_last, undo_last, mask."""
    TAP_SECS = 0.30          # a press shorter than this is a tap, not a dictation
    DOUBLE_TAP_SECS = 0.45   # second tap within this of the first -> hands-free

    def __init__(self, cfg, emit, clock=time.monotonic):
        self.emit = emit
        self.down = set()
        self.recording = False
        self.locked = False       # hands-free
        self.command = False
        self.paused = False
        self.clock = clock
        self.pressed_at = 0.0
        self.last_tap = -10.0
        # held shortcut keys that Windows was told are already up (so instant text can type while you hold
        # them): their auto-repeat and their real release are swallowed so Windows never sees them again
        self.released_mods = set()
        self.configure(cfg)

    def configure(self, cfg):
        self.ptt = parse(cfg.get("hotkey_ptt", "ctrl+win"))
        self.hf = parse(cfg.get("hotkey_handsfree_key", "space"))[0]
        self.cmd = parse(cfg.get("hotkey_command_key", "alt"))[0]
        self.cancel_key = parse(cfg.get("hotkey_cancel", "esc"))[0]
        self.paste_last = parse(cfg.get("hotkey_paste_last", "alt+shift+z"))
        self.undo_last = parse(cfg.get("hotkey_undo_last", "alt+shift+x"))
        self.double_tap = bool(cfg.get("double_tap_handsfree", True))
        self.ptt_vks = set().union(*self.ptt)

    def _held(self, groups):
        return all(self.down & g for g in groups)

    def reset(self):
        self.recording = self.locked = self.command = False

    def on_key(self, vk, is_down):
        """Returns True to swallow the key."""
        if is_down:
            repeat = vk in self.down
            self.down.add(vk)
        else:
            self.down.discard(vk)
            repeat = False
        if self.paused:
            return False
        return self._down(vk, repeat) if is_down else self._up(vk)

    def release_held(self):
        """Mark the shortcut keys held right now as released-to-Windows; returns them (to send their key-ups)."""
        held = set(self.down & self.ptt_vks) if self.recording else set()
        self.released_mods = self.released_mods | held
        return held

    def _down(self, vk, repeat):
        if vk in self.released_mods:  # still held after we told Windows it's up: keep it that way
            return True
        if repeat:  # auto-repeat: keep swallowing what we swallowed the first time
            return self.recording and (vk in self.hf or (vk in self.ptt_vks and vk not in MODIFIER_VKS))
        if not self.recording:
            if self._held(self.paste_last) and vk in self.paste_last[-1]:
                self.emit("paste_last", self.command)
                self.emit("mask", self.command)  # Alt+Shift alone on release would switch keyboard language
                return True
            if self._held(self.undo_last) and vk in self.undo_last[-1]:
                self.emit("undo_last", self.command)
                self.emit("mask", self.command)
                return True
            others = self.down - self.ptt_vks
            if self._held(self.ptt) and vk in self.ptt_vks and not (others - MODIFIER_VKS):
                now = self.clock()
                double = self.double_tap and now - self.last_tap < self.DOUBLE_TAP_SECS
                self.recording, self.locked = True, False
                self.released_mods = set()
                self.command = bool(self.down & self.cmd)
                self.pressed_at, self.last_tap = now, -10.0
                self.emit("start", self.command)
                if double:  # tap, tap -> hands-free
                    self.locked = True
                    self.emit("lock", self.command)
                if self.down & (WIN | ALT):
                    self.emit("mask", self.command)  # stop the Start menu / menu bar from opening on release
                return vk not in MODIFIER_VKS
            return False
        # --- while recording ---
        if vk in self.cancel_key:
            self.reset()
            self.emit("cancel", self.command)
            return False
        if self.locked:
            if self._held(self.ptt) and vk in self.ptt_vks:
                cmd = self.command
                self.reset()
                if self.down & (WIN | ALT):
                    self.emit("mask", cmd)
                self.emit("stop", cmd)
                return vk not in MODIFIER_VKS
            if vk in self.cmd and self._held(self.ptt):
                self.command = True
                self.emit("command", self.command)
                self.emit("mask", self.command)
            return False
        if vk in self.hf and self._held(self.ptt):
            self.locked = True
            self.emit("lock", self.command)
            return True
        if vk in self.cmd:
            if not self.command:
                self.command = True
                self.emit("command", self.command)
            self.emit("mask", self.command)
            return False
        if vk in self.ptt_vks or vk in SHIFT:
            return False
        # any other key while holding the shortcut = the user meant a different shortcut (e.g. Ctrl+Win+D)
        self.reset()
        self.emit("cancel", self.command)
        return False

    def _up(self, vk):
        swallow = vk in self.released_mods   # Windows already got this key's release from us
        self.released_mods.discard(vk)
        if self.recording and not self.locked and vk in self.ptt_vks and not self._held(self.ptt):
            self.recording = False
            now = self.clock()
            self.last_tap = now if now - self.pressed_at < self.TAP_SECS else -10.0
            self.emit("stop", self.command)
            return swallow or vk not in MODIFIER_VKS
        return swallow
