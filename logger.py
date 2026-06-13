"""Thread-safe logging system for FH6 Sniper GUI.

Functions:
- init_logger(): Initialize logger with Tkinter text widget
- update_log(): Thread-safe logging that updates GUI and file
"""

# -------------------------
# LOGGER
# -------------------------

# how many lines to keep in the GUI widget before trimming; raised
# from 100 to 10,000 so the user can scroll back further without
# immediately losing history.  We also mirror every message to a file
# in case the process needs to be re-opened later.
MAX_LOG_LINES = 10_000

# path of the persistent log file (appends, no rotation)
LOG_FILE = "sniper.log"

log_widget = None


def _update_log_impl(message):
    """Synchronous insertion into the log widget.

    This is the original logic extracted from ``update_log`` so that the
    public method can simply schedule it via ``after`` when called from a
    worker thread.  The implementation is unchanged except for the absence of
    thread-safety boilerplate.
    """
    global log_widget
    if log_widget is None:
        print(message)
        return

    # Determine icon and tag
    icon = None
    tag = None

    # Known emoji -> color mapping
    emoji_map = {
        "✅": "icon_green",
        "❌": "icon_red",
        "⚠️": "icon_yellow",
        "🛑": "icon_red",
        "🚀": "icon_blue",
        "🔄": "icon_blue",
        "🔴": "icon_red",
        "🟢": "icon_green",
        "⏱️": "icon_gray",
    }

    # If message already starts with an emoji token (separated by space), color that
    parts = message.split(" ", 1)
    if parts and parts[0] in emoji_map:
        icon = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        tag = emoji_map.get(icon)
    else:
        rest = message

    # If no leading emoji, check keywords to insert small colored icon
    if icon is None:
        low = message.lower()
        if "no car" in low or "refresh" in low:
            icon = "🔴"
            tag = "icon_red"
        elif "car found" in low or "buying" in low:
            icon = "🟢"
            tag = "icon_green"
        elif "buy successful" in low:
            icon = "✅"
            tag = "icon_green"
        elif "buy failed" in low:
            icon = "❌"
            tag = "icon_red"
        elif "starting" in low:
            icon = "🚀"
            tag = "icon_blue"
        elif "stopped" in low:
            icon = "🔄"
            tag = "icon_gray"

    try:
        log_widget.configure(state="normal")

        if icon:
            # Insert icon with tag, then the rest of the message untagged
            log_widget.insert("end", icon + " ", tag)
            log_widget.insert("end", rest + "\n")
        else:
            log_widget.insert("end", message + "\n")

        # Trim log lines to MAX_LOG_LINES
        try:
            total_lines = int(log_widget.index("end-1c").split(".")[0])
            if total_lines > MAX_LOG_LINES:
                # delete from line 1 to the amount to remove
                remove_lines = total_lines - MAX_LOG_LINES
                log_widget.delete("1.0", f"{remove_lines + 1}.0")
        except Exception:
            pass

        log_widget.see("end")
        log_widget.configure(state="disabled")
    except Exception:
        # If any UI error, fallback to printing
        try:
            print(message)
        except Exception:
            pass


def init_logger(widget):
    """Initialize the logger with a Tkinter Text-like widget."""
    global log_widget
    log_widget = widget

    # Configure tags for colored icons
    try:
        log_widget.tag_configure("icon_red", foreground="red")
        log_widget.tag_configure("icon_green", foreground="green")
        log_widget.tag_configure("icon_yellow", foreground="orange")
        log_widget.tag_configure("icon_blue", foreground="blue")
        log_widget.tag_configure("icon_gray", foreground="gray")
    except Exception:
        pass


def update_log(message):
    """Thread-safe wrapper that posts the real work to the GUI thread."""
    global log_widget
    if log_widget is None:
        print(message)
        return
    try:
        log_widget.after(0, lambda: _update_log_impl(message))
    except Exception:
        # if scheduling fails, just do it synchronously
        _update_log_impl(message)
    # always mirror to the file as well, since the GUI buffer is volatile
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass
