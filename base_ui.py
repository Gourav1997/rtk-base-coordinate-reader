"""Small Tkinter UI for extract_base.py. Run with python base_ui.py."""

from pathlib import Path
import os
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
import sys
from zipfile import ZipFile
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from tkintermapview import TkinterMapView
from tkintermapview.utility_functions import decimal_to_osm
import requests

from extract_base import extract, format_results, time_label

ESRI_TILES = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
TABLE_COLUMNS = (
    ('position', 'Base', 55),
    ('latitude', 'Latitude (deg)', 130),
    ('longitude', 'Longitude (deg)', 135),
    ('altitude', 'Ellipsoidal altitude (m)', 150),
    ('first', 'First received (UTC)', 230),
    ('last', 'Last received (UTC)', 230),
    ('count', 'Count', 65),
    ('stations', 'Station IDs', 95),
    ('types', 'RTCM types', 95),
)


def prepare_tk():
    """Support Windows Python installs shipping zipped Tcl/Tk libraries."""
    if getattr(sys, 'frozen', False):
        return  # PyInstaller configures the bundled Tcl/Tk libraries.
    support = Path(sys.base_prefix) / 'tcl'
    cache = Path(__file__).resolve().parent / '.tk-runtime'
    for name, variable in (('tcl', 'TCL_LIBRARY'), ('tk', 'TK_LIBRARY')):
        if variable in os.environ or list(support.glob(f'{name}*/init.tcl')):
            continue
        archives = sorted(support.glob(f'lib{name}*.zip'))
        if archives:
            target = cache / archives[-1].stem
            if not (target / f'{name}_library').is_dir():
                with ZipFile(archives[-1]) as archive:
                    archive.extractall(target)
            os.environ[variable] = str(target / f'{name}_library')


class BaseWindow:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.results = Queue()
        self.map_checks = Queue()
        self.map_generation = 0
        self.positions = []
        root.title('RTK Base Coordinate Reader')
        root.geometry('1200x700')
        root.minsize(900, 520)
        tabs = ttk.Notebook(root)
        tabs.pack(fill='both', expand=True)
        panel = ttk.Frame(tabs, padding=18)
        tabs.add(panel, text='Base Reader')
        about = ttk.Frame(tabs, padding=30)
        tabs.add(about, text='About Us')
        ttk.Label(about, text='RTK Base Coordinate Reader',
                  font=('Segoe UI', 20, 'bold')).pack(anchor='w', pady=(0, 16))
        ttk.Label(about, text=(
            'Extract RTK base station latitude, longitude, and ellipsoidal altitude '
            'from ArduPilot MAVLink .tlog files. View unique base positions, timestamps, '
            'and observation counts, and locate the base on an Esri satellite map '
            'to compare it with your known location.'),
            wraplength=700, justify='left', font=('Segoe UI', 11)).pack(anchor='w')
        ttk.Label(about, text='Developer: GouravD',
                  font=('Segoe UI', 12, 'bold')).pack(anchor='w', pady=(24, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(5, weight=1)
        panel.rowconfigure(6, weight=3)
        ttk.Label(panel, text='RTK Base Coordinate Reader',
                  font=('Segoe UI', 16, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(panel, text='Choose a MAVLink .tlog file to read its base station coordinates.').grid(
            row=1, column=0, columnspan=3, sticky='w', pady=(6, 16))
        self.path = tk.StringVar(value='')
        self.entry = ttk.Entry(panel, textvariable=self.path)
        self.entry.grid(row=2, column=0, sticky='ew')
        self.browse = ttk.Button(panel, text='Browse…', command=self.choose_file)
        self.browse.grid(row=2, column=1, padx=8)
        self.read = ttk.Button(panel, text='Read file', command=self.start)
        self.read.grid(row=2, column=2)
        self.status = tk.StringVar(value='Ready')
        ttk.Label(panel, textvariable=self.status).grid(row=3, column=0, columnspan=3,
                                                       sticky='w', pady=(12, 5))
        self.progress = ttk.Progressbar(panel, mode='indeterminate')
        self.progress.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(0, 12))
        table_panel = ttk.Frame(panel)
        table_panel.grid(row=5, column=0, columnspan=3, sticky='nsew', pady=(0, 12))
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(table_panel)
        toolbar.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        ttk.Label(toolbar, text='Base positions', font=('Segoe UI', 11, 'bold')).pack(side='left')
        self.copy_selected = ttk.Button(toolbar, text='Copy selected rows', state='disabled',
                                        command=lambda: self.copy_table(selected=True))
        self.copy_selected.pack(side='left', padx=(16, 6))
        self.copy_all = ttk.Button(toolbar, text='Copy all rows', state='disabled', command=self.copy_table)
        self.copy_all.pack(side='left')
        ttk.Label(toolbar, text='Ctrl+C: copy rows  |  Double-click: copy a cell').pack(side='left', padx=12)
        self.table = ttk.Treeview(table_panel, columns=[column[0] for column in TABLE_COLUMNS],
                                  show='headings', selectmode='extended', height=5)
        for key, label, width in TABLE_COLUMNS:
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=width, stretch=False, anchor='w')
        self.table.grid(row=1, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(table_panel, orient='vertical', command=self.table.yview)
        vertical.grid(row=1, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(table_panel, orient='horizontal', command=self.table.xview)
        horizontal.grid(row=2, column=0, sticky='ew')
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.bind('<Control-c>', lambda event: self.copy_table(selected=True))
        self.table.bind('<Control-C>', lambda event: self.copy_table(selected=True))
        self.table.bind('<Double-1>', self.copy_cell)
        self.table.bind('<<TreeviewSelect>>', self.select_base_row)
        split = ttk.Panedwindow(panel, orient='horizontal')
        split.grid(row=6, column=0, columnspan=3, sticky='nsew')
        results_panel = ttk.Frame(split)
        map_panel = ttk.Frame(split)
        split.add(results_panel, weight=2)
        split.add(map_panel, weight=3)
        ttk.Label(results_panel, text='Details and diagnostics', font=('Segoe UI', 11, 'bold')).pack(
            anchor='w', pady=(0, 6))
        self.output = ScrolledText(results_panel, wrap='word', font=('Consolas', 11),
                                   height=9, width=45)
        self.output.pack(fill='both', expand=True)
        map_panel.columnconfigure(0, weight=1)
        map_panel.rowconfigure(1, weight=1)
        controls = ttk.Frame(map_panel, padding=(10, 0, 0, 8))
        controls.grid(row=0, column=0, sticky='ew')
        ttk.Label(controls, text='Base position:').pack(side='left')
        self.position_choice = ttk.Combobox(controls, state='disabled', width=18)
        self.position_choice.pack(side='left', padx=8)
        self.position_choice.bind('<<ComboboxSelected>>', lambda event: self.center_base())
        ttk.Button(controls, text='Center on base', command=self.center_base).pack(side='left')
        # Avoid default-provider requests during widget initialization.
        self.map = TkinterMapView(map_panel, width=560, height=420, corner_radius=0,
                                  use_database_only=True)
        self.map.set_tile_server(ESRI_TILES, max_zoom=19)
        self.map.use_database_only = False
        self.map.set_position(22.5, 79.0)
        self.map.set_zoom(4)
        self.map.grid(row=1, column=0, sticky='nsew', padx=(10, 0))
        self.map_status = tk.StringVar(value='Read a log to show the base. Drag to pan; scroll or use + / - to zoom.')
        ttk.Label(map_panel, textvariable=self.map_status, wraplength=560).grid(
            row=2, column=0, sticky='w', padx=10, pady=(6, 2))
        ttk.Label(map_panel, text='Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community',
                  wraplength=560).grid(row=3, column=0, sticky='w', padx=10)
        self.show('Select a file, then click Read file.\n\nResults will appear here.')
        self.entry.bind('<Return>', lambda event: self.start())
        self.root.after(200, self.poll_imagery)

    def show_positions(self, positions):
        self.map_generation += 1
        self.positions = list(positions.values())
        self.table.delete(*self.table.get_children())
        for i, position in enumerate(self.positions, 1):
            lat, lon, alt = position['llh']
            self.table.insert('', 'end', iid=str(i), values=(
                i, f'{lat:.10f}', f'{lon:.10f}', f'{alt:.4f}',
                time_label(position['first']), time_label(position['last']), position['count'],
                ', '.join(map(str, sorted(position['stations']))), ', '.join(sorted(position['types']))))
        for button in (self.copy_selected, self.copy_all):
            button.configure(state='normal' if self.positions else 'disabled')
        self.map.delete_all_marker()
        self.position_choice.set('')
        self.position_choice.configure(values=[f'Position {i}' for i in range(1, len(self.positions) + 1)],
                                        state='readonly' if self.positions else 'disabled')
        for i, position in enumerate(self.positions, 1):
            lat, lon, alt = position['llh']
            self.map.set_marker(lat, lon, text=f'Base {i} | {alt:.2f} m',
                                text_color='white', marker_color_circle='#ffffff',
                                marker_color_outside='#d7263d')
        if self.positions:
            self.position_choice.current(0)
            self.table.selection_set('1')
            self.center_base()
        else:
            self.map_status.set('No base positions to display.')

    def copy_table(self, selected=False):
        selection = set(self.table.selection())
        rows = [row for row in self.table.get_children() if not selected or row in selection]
        if rows:
            text = '\t'.join(column[1] for column in TABLE_COLUMNS) + '\n'
            text += '\n'.join('\t'.join(map(str, self.table.item(row, 'values'))) for row in rows)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status.set(f'Copied {len(rows)} row(s). Paste into a spreadsheet or text editor.')
        return 'break'

    def copy_cell(self, event):
        row = self.table.identify_row(event.y)
        column = self.table.identify_column(event.x)
        if row and column and self.table.identify_region(event.x, event.y) == 'cell':
            value = self.table.item(row, 'values')[int(column[1:]) - 1]
            self.root.clipboard_clear()
            self.root.clipboard_append(str(value))
            self.status.set('Copied cell value.')
            return 'break'

    def select_base_row(self, event=None):
        selection = self.table.selection()
        if selection:
            index = int(selection[0]) - 1
            if index != self.position_choice.current():
                self.position_choice.current(index)
                self.center_base()

    def center_base(self):
        index = self.position_choice.current()
        if not 0 <= index < len(self.positions):
            return
        row = str(index + 1)
        if row not in self.table.selection():
            self.table.selection_set(row)
            self.table.see(row)
        lat, lon, _ = self.positions[index]['llh']
        self.map.set_position(lat, lon)
        self.map.set_zoom(18)
        self.map_generation += 1
        generation = self.map_generation
        self.map_status.set(f'Base {index + 1}: {lat:.10f}, {lon:.10f} | Loading Esri imagery…')
        Thread(target=self.check_imagery, args=(lat, lon, generation), daemon=True).start()

    def check_imagery(self, lat, lon, generation):
        x, y = decimal_to_osm(lat, lon, 18)
        try:
            response = requests.get(ESRI_TILES.format(z=18, x=int(x), y=int(y)), timeout=10)
            response.raise_for_status()
            if not response.headers.get('Content-Type', '').startswith('image/'):
                raise ValueError('Esri did not return an image')
            note = 'Esri satellite imagery | Drag to pan; scroll or use + / - to zoom.'
        except (requests.RequestException, ValueError):
            note = 'Esri imagery unavailable. Check your internet connection, then click Center on base to retry.'
        self.map_checks.put((generation, note))

    def poll_imagery(self):
        try:
            while True:
                generation, note = self.map_checks.get_nowait()
                if generation == self.map_generation:
                    self.map_status.set(note)
        except Empty:
            pass
        self.root.after(200, self.poll_imagery)

    def show(self, text):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)
        self.output.configure(state='disabled')

    def choose_file(self):
        current = Path(self.path.get()).expanduser()
        selected = filedialog.askopenfilename(
            parent=self.root, title='Select MAVLink telemetry log',
            initialdir=str(current.parent if current.is_file() else Path.home() / 'Downloads'),
            filetypes=[('MAVLink logs', '*.tlog'), ('All files', '*.*')])
        if selected:
            self.path.set(selected)

    def start(self):
        if self.busy:
            return
        path = Path(self.path.get().strip().strip('"')).expanduser()
        if not path.is_file():
            self.status.set('Please select an existing file.')
            self.show(f'File not found:\n{path}')
            return
        self.busy = True
        self.show_positions({})
        for widget in (self.entry, self.browse, self.read):
            widget.configure(state='disabled')
        self.status.set('Reading log…')
        self.show(f'Reading {path.name}…')
        self.progress.start(12)
        Thread(target=self.work, args=(path,), daemon=True).start()
        self.root.after(100, self.poll)

    def work(self, path):
        # Only the main thread touches Tk; parsing runs in the background.
        try:
            positions, stats = extract(path)
            self.results.put((f'Found {len(positions)} unique base position(s).' if positions
                              else 'Finished — no base positions found.', self.details(positions, stats), positions))
        except Exception as exc:
            self.results.put(('Could not read file.', f'{type(exc).__name__}: {exc}', {}))

    @staticmethod
    def details(positions, stats):
        if not positions:
            return format_results(positions, stats)
        return (f'{len(positions)} unique base position(s) found.\n'
                'First and last timestamps are log receive times in UTC, not GNSS measurement times.\n'
                'Count is the number of RTCM 1005/1006 observations for each position.\n\n'
                'Diagnostics: ' + ', '.join(f'{key}={value}' for key, value in sorted(stats.items())) + '\n\n'
                'Altitude is WGS84 ellipsoidal height of the antenna reference point (ARP), not mean sea level.\n'
                'RTCM 1006 antenna height is not added to the ARP coordinates.')

    def poll(self):
        try:
            status, output, positions = self.results.get_nowait()
        except Empty:
            self.root.after(100, self.poll)
            return
        self.progress.stop()
        self.status.set(status)
        self.show(output)
        self.show_positions(positions)
        self.busy = False
        for widget in (self.entry, self.browse, self.read):
            widget.configure(state='normal')


if __name__ == '__main__':
    prepare_tk()
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        from verify_bundle import verify
        sys.exit(verify(sys.argv[2], sys.argv[3]))
    window = tk.Tk()
    BaseWindow(window)
    window.mainloop()
