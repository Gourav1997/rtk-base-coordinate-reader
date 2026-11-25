"""Exercise the packaged GUI: app.exe --self-test INPUT.tlog REPORT.json."""

import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
import traceback


def verify(log_path, report_path):
    from base_ui import BaseWindow

    report = {}
    root = None
    deadline = time.monotonic() + 90
    try:
        root = tk.Tk()
        root.withdraw()
        app = BaseWindow(root)
        assert app.path.get() == ''
        app.path.set(log_path)

        def finish():
            try:
                if app.busy:
                    if time.monotonic() > deadline:
                        raise TimeoutError('Log extraction timed out')
                    root.after(100, finish)
                    return
                tabs = next(widget for widget in root.winfo_children() if isinstance(widget, ttk.Notebook))
                labels = [tabs.tab(tab, 'text') for tab in tabs.tabs()]
                assert 'About Us' in labels
                assert app.positions, app.output.get('1.0', 'end')
                assert len(app.map.canvas_marker_list) == len(app.positions)
                rows = app.table.get_children()
                assert len(rows) == len(app.positions)
                app.copy_table()
                copied = root.clipboard_get()
                assert 'First received (UTC)' in copied
                assert 'Last received (UTC)' in copied
                report.update(ok=True, tabs=labels, positions=len(app.positions),
                              markers=len(app.map.canvas_marker_list),
                              table=[app.table.item(row, 'values') for row in rows],
                              clipboard=copied,
                              output=app.output.get('1.0', 'end').strip())
            except Exception:
                report.update(ok=False, error=traceback.format_exc())
            root.destroy()

        app.start()
        root.after(100, finish)
        root.mainloop()
    except Exception:
        report.update(ok=False, error=traceback.format_exc())
        if root:
            root.destroy()
    Path(report_path).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report.get('ok') else 1
