"""Any other system (Linux, used for testing): the osapi interface doing nothing, so the app opens and the
self-test runs. Nothing is typed into other apps; this is the reference list of what win.py and mac.py provide."""
import subprocess
import threading

OS_NAME = "this computer"
PASTE_KEYS = "Ctrl+V"
CAN_RELEASE_KEYS = False


# ------------------------------------------------------------------ process
def prepare_process():
    pass


def tk_ready(root):
    pass


def startup_enabled():
    return False


def set_startup(enabled, script_path, icon_path=""):
    pass


def single_instance():
    return True


def ask_running_instance_to_open():
    return False


def watch_open_requests(callback):
    pass


def wait_for_exit(pid, timeout_ms):
    pass


def show_message(text, title="Aqua Lite"):
    print(f"{title}: {text}")


def open_path(path):
    subprocess.Popen(["xdg-open", path])


def open_folder(path):
    subprocess.Popen(["xdg-open", path])


def play_sound(path):
    pass


def activate_app():
    pass


def permission_problems():
    return []


def open_permission_settings(kind):
    pass


def self_elevated():
    return False


def process_elevated(pid):
    return False


def close_with_us(popen):
    pass


# ------------------------------------------------------------------ keyboard
class KeyboardHook(threading.Thread):
    """No global shortcuts here."""

    def __init__(self, handler):
        super().__init__(daemon=True, name="keyboard-hook")
        self.handler = handler
        self.ok = threading.Event()
        self.error = "global shortcuts aren't available on this system"

    def run(self):
        self.ok.set()

    def stop(self):
        pass


def send_mask():
    pass


def release_keys(vks):
    pass


def type_text(text):
    return False


def tap_key(name, times=1):
    pass


def select_left(count):
    return False


def press_enter():
    pass


def undo_insert(text, proc):
    return "none"


def wait_modifiers_released(timeout=2.0):
    return True


# ------------------------------------------------------------------ the focused app & clipboard
def foreground():
    return "demo", "", 0


def foreground_window():
    return 0


def paste(text, cfg, target=None, saved=None, queued=0):
    return {"proc": (target or foreground())[0], "keys": "none", "delay": 0, "status": "demo"}


def copy_selection(timeout=0.5):
    return "", None


def set_text(text, private=True):
    return 0


def get_text():
    return ""


def snapshot():
    return None


def restore(items):
    return False


def sequence():
    return 0


# ------------------------------------------------------------------ reading text boxes
def text_before_caret(n):
    return None, False


def selected_text():
    return None


def is_password_box():
    return False


def text_reader():
    raise ImportError("reading text boxes isn't available on this system")


def read_window(window, max_elements):
    raise ImportError("reading windows isn't available on this system")


# ------------------------------------------------------------------ windows on screen
def window_handle(tk_window):
    return tk_window.winfo_id()


def dpi_scale(tk_window):
    return 1.0


Overlay = None   # no see-through window: the Flow bar draws into its Tk canvas
Frost = None


def frost_available():
    return False


def frost_supported():
    return False


def transparency_on():
    return True


def animations_on():
    return True


def apps_light_theme():
    return True


def watch_theme(callback):
    pass


def display_timing():
    raise OSError("no display timing here")


def fine_timer(on):
    pass


def work_area_at_cursor():
    raise OSError("no work area here")


def title_bar(tk_window, dark, caption, text=None, border=None):
    pass

