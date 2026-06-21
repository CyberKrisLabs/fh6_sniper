from PySide6.QtCore import QObject, Signal


class _LogBridge(QObject):
    message = Signal(str)


_log_bridge = _LogBridge()


def _emit_log(msg: str) -> None:
    _log_bridge.message.emit(msg)
