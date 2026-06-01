import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from tkinterdnd2 import TkinterDnD, DND_FILES
import socket
import threading
import struct
import os
import sys
import time
import tempfile
import shutil

# OS別フォント（日本語が確実に表示されるフォントを指定）
if sys.platform == "win32":
    FONT_UI   = ("Yu Gothic UI", 10)
    FONT_CHAT = ("Yu Gothic UI", 11)
    FONT_SMALL = ("Yu Gothic UI", 9)
    DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
else:
    FONT_UI    = ("", 11)
    FONT_CHAT  = ("", 11)
    FONT_SMALL = ("", 9)
    DOWNLOADS  = os.path.expanduser("~/Downloads")

PORT      = 5050
DISC_PORT = 5051   # UDP ブロードキャスト用
CHUNK_SIZE = 65536

MSG_TYPE  = b'\x01'
FILE_TYPE = b'\x02'
DISC_MSG  = b'P2PCHAT_HELLO'


# ------------------------------------------------------------------ カラーパレット
DARK = {
    "bg":          "#1e1e2e",
    "panel":       "#2a2a3e",
    "border":      "#44475a",
    "input_bg":    "#313244",
    "text":        "#cdd6f4",
    "text_dim":    "#6c7086",
    "self_msg":    "#89b4fa",
    "peer_msg":    "#a6e3a1",
    "system_msg":  "#585b70",
    "btn_bg":      "#45475a",
    "btn_fg":      "#cdd6f4",
    "btn_active":  "#585b70",
    "accent":      "#89b4fa",
    "accent_fg":   "#1e1e2e",
    "ok":          "#a6e3a1",
    "warn":        "#fab387",
    "err":         "#f38ba8",
    "drop_hover":  "#3a3a5e",
}


class RoundedButton(tk.Canvas):
    """Canvas で描く角丸ボタン"""

    def __init__(self, parent, text, command, accent=False,
                 width=None, height=32, radius=10, **kw):
        bg_parent = parent.cget("bg")
        if width is None:
            width = len(text) * 14 + 40
        super().__init__(parent, width=width, height=height,
                         bg=bg_parent, highlightthickness=0, **kw)
        self._command  = command
        self._radius   = radius
        self._width    = width
        self._height   = height
        self._accent   = accent
        self._text     = text
        self._disabled = False

        self._color_normal = DARK["accent"]  if accent else DARK["btn_bg"]
        self._color_hover  = "#a6c8ff"       if accent else DARK["border"]
        self._color_fg     = DARK["accent_fg"] if accent else DARK["btn_fg"]
        self._color_dis    = DARK["border"]

        self._draw(self._color_normal)
        self.bind("<Enter>",           self._on_enter)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, fill):
        self.delete("all")
        r, w, h = self._radius, self._width, self._height
        self.create_arc(0,     0,     r*2, r*2, start=90,  extent=90,  fill=fill, outline=fill)
        self.create_arc(w-r*2, 0,     w,   r*2, start=0,   extent=90,  fill=fill, outline=fill)
        self.create_arc(0,     h-r*2, r*2, h,   start=180, extent=90,  fill=fill, outline=fill)
        self.create_arc(w-r*2, h-r*2, w,   h,   start=270, extent=90,  fill=fill, outline=fill)
        self.create_rectangle(r, 0,   w-r, h,   fill=fill, outline=fill)
        self.create_rectangle(0, r,   w,   h-r, fill=fill, outline=fill)
        fg = DARK["text_dim"] if self._disabled else self._color_fg
        self.create_text(w//2, h//2, text=self._text, fill=fg, font=FONT_CHAT)

    def _on_enter(self, _):
        if not self._disabled:
            self._draw(self._color_hover)

    def _on_leave(self, _):
        if not self._disabled:
            self._draw(self._color_normal)

    def _on_press(self, _):
        if not self._disabled:
            self._draw(DARK["border"])

    def _on_release(self, _):
        if not self._disabled:
            self._draw(self._color_hover)
            self._command()

    def config(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        if "state" in kw:
            self._disabled = (kw["state"] == tk.DISABLED)
            fill = self._color_dis if self._disabled else self._color_normal
            self._draw(fill)
        else:
            super().config(**kw)

    def configure(self, cnf=None, **kw):
        self.config(cnf, **kw)


class P2PApp:
    def __init__(self, root):
        self.root = root
        self.root.title("P2P チャット")
        self.root.geometry("660x780")
        self.root.resizable(True, True)
        self.root.configure(bg=DARK["bg"])

        self.conn = None
        self.server_socket = None
        self._peers = {}            # ip -> (hostname, last_seen, is_waiting)
        self._my_ip = self._get_local_ip()
        self._pending_file = None
        self._my_state = "idle"     # "idle" or "waiting"

        self._apply_ttk_style()
        self._build_ui()
        self._start_discovery()

    def _apply_ttk_style(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("dark.Horizontal.TProgressbar",
            troughcolor=DARK["panel"],
            background=DARK["accent"],
            bordercolor=DARK["border"],
            lightcolor=DARK["accent"],
            darkcolor=DARK["accent"],
        )

    # ================================================================ UI

    def _btn(self, parent, text, command, accent=False, **kw):
        return RoundedButton(parent, text=text, command=command,
                             accent=accent, height=32)

    def _label(self, parent, text, dim=False, **kw):
        fg = DARK["text_dim"] if dim else DARK["text"]
        return tk.Label(parent, text=text, bg=parent["bg"], fg=fg, **kw)

    def _build_ui(self):
        D = DARK

        def frame(parent, **kw):
            return tk.Frame(parent, bg=D["panel"], **kw)

        def lframe(parent, text):
            return tk.LabelFrame(parent, text=text,
                                 bg=D["panel"], fg=D["text_dim"],
                                 bd=1, relief=tk.SOLID,
                                 highlightbackground=D["border"],
                                 padx=8, pady=6)

        # --- 接続エリア ---
        conn_frame = lframe(self.root, "接続")
        conn_frame.pack(fill=tk.X, padx=10, pady=(10, 4))

        list_row = frame(conn_frame)
        list_row.pack(fill=tk.X)

        self._label(list_row, "検出された相手:").pack(side=tk.LEFT)

        self.peer_var = tk.StringVar(value="（未検出）")
        self._peer_menu_obj = tk.Menu(list_row, tearoff=0,
                                      bg=D["input_bg"], fg=D["text"],
                                      activebackground=D["accent"],
                                      activeforeground=D["accent_fg"],
                                      bd=0)
        self.peer_combo = tk.Menubutton(
            list_row, textvariable=self.peer_var,
            menu=self._peer_menu_obj,
            bg=D["input_bg"], fg=D["text"],
            activebackground=D["border"], activeforeground=D["text"],
            relief=tk.FLAT,
            highlightthickness=1, highlightbackground=D["border"],
            width=24, anchor=tk.W, padx=6,
        )
        self.peer_combo.pack(side=tk.LEFT, padx=4)
        self._btn(list_row, "↺ 更新", self._refresh_peers).pack(side=tk.LEFT)

        manual_row = frame(conn_frame)
        manual_row.pack(fill=tk.X, pady=(6, 0))

        self._label(manual_row, "手動IP入力:").pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(manual_row, width=16,
                                 bg=D["input_bg"], fg=D["text"],
                                 insertbackground=D["text"],
                                 relief=tk.FLAT, bd=4)
        self.ip_entry.pack(side=tk.LEFT, padx=4)
        self.ip_entry.bind("<Return>", lambda e: self._connect())
        self._label(manual_row, "（リストに出ない場合）",
                    dim=True, font=FONT_SMALL).pack(side=tk.LEFT)

        btn_row = frame(conn_frame)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        self.connect_btn = self._btn(btn_row, "接続する", self._connect, accent=True)
        self.connect_btn.pack(side=tk.LEFT)
        self.connect_btn.config(state=tk.DISABLED)
        self._label(btn_row, "または", dim=True).pack(side=tk.LEFT, padx=10)
        self.wait_btn = self._btn(btn_row, "待機する", self._start_server)
        self.wait_btn.pack(side=tk.LEFT)

        self.status_label = tk.Label(conn_frame, text="● 未接続",
                                     bg=D["panel"], fg=D["text_dim"])
        self.status_label.pack(anchor=tk.W, pady=(6, 0))

        # --- チャットエリア ---
        self.chat_area = scrolledtext.ScrolledText(
            self.root, state=tk.DISABLED, wrap=tk.WORD,
            height=8, padx=8, pady=6, font=FONT_CHAT,
            bg=D["panel"], fg=D["text"],
            insertbackground=D["text"],
            selectbackground=D["border"],
            relief=tk.FLAT, bd=0,
        )
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self.chat_area.tag_config("self",   foreground=D["self_msg"])
        self.chat_area.tag_config("peer",   foreground=D["peer_msg"])
        self.chat_area.tag_config("system", foreground=D["system_msg"],
                                  font=(*FONT_SMALL, "italic"))

        # テキスト選択・コピーを有効化
        self.chat_area.bind("<Button-1>", lambda e: self.chat_area.focus_set())
        copy_key = "<Command-c>" if sys.platform == "darwin" else "<Control-c>"
        self.chat_area.bind(copy_key, self._copy_selected)

        # 右クリックメニュー
        self._chat_menu = tk.Menu(self.chat_area, tearoff=0,
                                  bg=DARK["input_bg"], fg=DARK["text"],
                                  activebackground=DARK["accent"],
                                  activeforeground=DARK["accent_fg"])
        self._chat_menu.add_command(label="コピー", command=self._copy_selected)
        self._chat_menu.add_command(label="すべて選択", command=self._select_all)
        if sys.platform == "darwin":
            self.chat_area.bind("<Button-2>",         self._show_chat_menu)
            self.chat_area.bind("<Button-3>",         self._show_chat_menu)
            self.chat_area.bind("<Control-Button-1>", self._show_chat_menu)
        else:
            self.chat_area.bind("<Button-3>", self._show_chat_menu)

        # --- プログレスバー ---
        prog_frame = tk.Frame(self.root, bg=D["bg"], padx=10)
        prog_frame.pack(fill=tk.X)
        self.progress_label = tk.Label(prog_frame, text="", anchor=tk.W,
                                       font=FONT_SMALL,
                                       bg=D["bg"], fg=D["text_dim"])
        self.progress_label.pack(fill=tk.X)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(prog_frame,
                                            style="dark.Horizontal.TProgressbar",
                                            variable=self.progress_var,
                                            maximum=100)
        self.progress_bar.pack(fill=tk.X)

        # --- ファイル送信エリア（ドラッグ＆ドロップ） ---
        file_frame = lframe(self.root, "ファイル送信")
        file_frame.pack(fill=tk.X, padx=10, pady=(4, 4))

        self.drop_label = tk.Label(
            file_frame,
            text="ここにファイルをドラッグ＆ドロップ",
            bg=D["input_bg"], fg=D["text_dim"],
            relief=tk.FLAT, pady=14, font=FONT_SMALL,
            cursor="hand2",
        )
        self.drop_label.pack(fill=tk.X, padx=2, pady=(0, 6))

        # D&D登録
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind("<<Drop>>",         self._on_file_drop)
        self.drop_label.dnd_bind("<<DragEnter>>",    self._on_drag_enter)
        self.drop_label.dnd_bind("<<DragLeave>>",    self._on_drag_leave)

        file_btn_row = frame(file_frame)
        file_btn_row.pack(fill=tk.X)

        self.clear_file_btn = self._btn(file_btn_row, "✕ クリア", self._clear_pending_file)
        self.clear_file_btn.pack(side=tk.LEFT)
        self.clear_file_btn.config(state=tk.DISABLED)

        self.file_send_btn = self._btn(file_btn_row, "送信", self._send_pending_file, accent=True)
        self.file_send_btn.pack(side=tk.RIGHT)
        self.file_send_btn.config(state=tk.DISABLED)

        # --- テキスト入力エリア ---
        input_frame = tk.Frame(self.root, bg=D["bg"], padx=10, pady=6)
        input_frame.pack(fill=tk.X)
        input_frame.columnconfigure(0, weight=1)

        self.msg_entry = tk.Entry(input_frame, font=FONT_CHAT,
                                  bg=D["input_bg"], fg=D["text"],
                                  insertbackground=D["text"],
                                  relief=tk.FLAT, bd=6)
        self.msg_entry.grid(row=0, column=0, sticky=tk.EW, padx=(0, 6))
        self.msg_entry.bind("<Return>", lambda e: self._send_message())

        self.send_btn = self._btn(input_frame, "送信", self._send_message,
                                  accent=True, width=7)
        self.send_btn.grid(row=0, column=1, pady=(0, 4))

    # ================================================================ ログ

    def _copy_selected(self, event=None):
        try:
            text = self.chat_area.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass  # 選択なし
        return "break"

    def _select_all(self, event=None):
        self.chat_area.tag_add(tk.SEL, "1.0", tk.END)
        self.chat_area.mark_set(tk.INSERT, "1.0")
        self.chat_area.see(tk.INSERT)

    def _show_chat_menu(self, event):
        self.chat_area.focus_set()
        self._chat_menu.tk_popup(event.x_root, event.y_root)

    def _log(self, text, tag="system"):
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, text + "\n", tag)
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)

    def _log_file_received(self, filename, tmp_path, filesize):
        """受信ファイルをクリック可能なボタンとしてチャットに追加"""
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, "  ", "system")
        btn = tk.Button(
            self.chat_area,
            text=f"📎 {filename}  ({self._human_size(filesize)})   ← クリックして保存",
            command=lambda p=tmp_path, n=filename: self._save_received_file(p, n),
            bg=DARK["input_bg"], fg=DARK["accent"],
            activebackground=DARK["border"], activeforeground=DARK["accent"],
            relief=tk.FLAT, cursor="hand2", font=FONT_SMALL, bd=0, padx=8, pady=4,
        )
        self.chat_area.window_create(tk.END, window=btn)
        self.chat_area.insert(tk.END, "\n", "system")
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)

    def _save_received_file(self, tmp_path, filename):
        save_path = filedialog.asksaveasfilename(
            initialfile=filename,
            title="保存先を選んでください",
        )
        if not save_path:
            return
        try:
            shutil.copy2(tmp_path, save_path)
            self._log(f"保存しました: {save_path}")
        except Exception as e:
            self._log(f"保存失敗: {e}")

    def _set_status(self, text, color=None):
        fg = color or DARK["text"]
        self.status_label.config(text=f"● {text}", fg=fg)

    def _on_disconnected(self):
        self._my_state = "idle"
        self._set_status("切断 — 再接続できます", DARK["err"])
        self.wait_btn.config(state=tk.NORMAL)
        self.conn = None
        self._update_connect_btn()

    def _cleanup_connection(self):
        """既存の接続・サーバーソケットを閉じる"""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

    def _set_connected(self, ip):
        self._my_state = "idle"
        self.root.after(0, self._set_status, f"接続中: {ip}", DARK["ok"])
        self.root.after(0, self.connect_btn.config, {"state": tk.DISABLED})
        self.root.after(0, self.wait_btn.config,    {"state": tk.DISABLED})

    # ================================================================ ドラッグ＆ドロップ

    def _on_drag_enter(self, event):
        self.drop_label.config(bg=DARK["drop_hover"], fg=DARK["text"])

    def _on_drag_leave(self, event):
        if self._pending_file:
            self.drop_label.config(bg=DARK["input_bg"], fg=DARK["text"])
        else:
            self.drop_label.config(bg=DARK["input_bg"], fg=DARK["text_dim"])

    def _on_file_drop(self, event):
        path = event.data.strip()
        # Windows: パスが {} で囲まれる場合がある
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        if not os.path.isfile(path):
            self._log(f"ファイルが見つかりません: {path}")
            return
        self._pending_file = path
        name = os.path.basename(path)
        size = self._human_size(os.path.getsize(path))
        self.drop_label.config(
            text=f"📎 {name}  ({size})",
            bg=DARK["input_bg"], fg=DARK["text"],
        )
        self.file_send_btn.config(state=tk.NORMAL)
        self.clear_file_btn.config(state=tk.NORMAL)

    def _clear_pending_file(self):
        self._pending_file = None
        self.drop_label.config(
            text="ここにファイルをドラッグ＆ドロップ",
            bg=DARK["input_bg"], fg=DARK["text_dim"],
        )
        self.file_send_btn.config(state=tk.DISABLED)
        self.clear_file_btn.config(state=tk.DISABLED)

    def _send_pending_file(self):
        if not self.conn:
            self._log("まだ接続されていません")
            return
        if not self._pending_file:
            return
        filepath = self._pending_file
        self._clear_pending_file()
        threading.Thread(target=self._send_file_thread,
                         args=(filepath,), daemon=True).start()

    # ================================================================ 自動検出

    def _start_discovery(self):
        threading.Thread(target=self._broadcast_loop,   daemon=True).start()
        threading.Thread(target=self._discovery_listen, daemon=True).start()
        self._cleanup_peers()

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        hostname = socket.gethostname().encode("utf-8")
        while True:
            try:
                state = self._my_state.encode("utf-8")
                payload = DISC_MSG + b"|" + hostname + b"|" + state
                sock.sendto(payload, ("255.255.255.255", DISC_PORT))
            except Exception:
                pass
            time.sleep(2)

    def _discovery_listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISC_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(256)
                if not data.startswith(DISC_MSG + b"|"):
                    continue
                ip = addr[0]
                if ip == self._my_ip:
                    continue
                parts = data[len(DISC_MSG) + 1:].decode("utf-8", errors="replace").split("|")
                hostname   = parts[0]
                is_waiting = len(parts) > 1 and parts[1] == "waiting"
                self._peers[ip] = (hostname, time.time(), is_waiting)
                self.root.after(0, self._refresh_peers)
            except Exception:
                pass

    def _cleanup_peers(self):
        now = time.time()
        expired = [ip for ip, (_, t, __) in self._peers.items() if now - t > 10]
        for ip in expired:
            del self._peers[ip]
        self._refresh_peers()
        self.root.after(6000, self._cleanup_peers)

    def _refresh_peers(self):
        entries = [(f"{hostname}  ({ip})", is_waiting)
                   for ip, (hostname, _, is_waiting) in self._peers.items()]
        self._peer_menu_obj.delete(0, tk.END)
        if entries:
            for label, _ in entries:
                self._peer_menu_obj.add_command(
                    label=label,
                    command=lambda v=label: (self.peer_var.set(v), self._update_connect_btn()))
            labels = [e[0] for e in entries]
            if self.peer_var.get() not in labels:
                self.peer_var.set(labels[0])
        else:
            self.peer_var.set("（未検出）")
        self._update_connect_btn()

    def _update_connect_btn(self):
        """選択中の相手が待機中のときだけ「接続する」を有効にする"""
        if self.conn:
            return
        ip = self._selected_ip()
        if ip and ip in self._peers and self._peers[ip][2]:
            self.connect_btn.config(state=tk.NORMAL)
        else:
            self.connect_btn.config(state=tk.DISABLED)

    def _selected_ip(self):
        manual = self.ip_entry.get().strip()
        if manual:
            return manual
        val = self.peer_var.get()
        if not val:
            return None
        return val.rsplit("(", 1)[-1].rstrip(")")

    # ================================================================ サーバー待機

    def _start_server(self):
        self._cleanup_connection()
        self._my_state = "waiting"
        self.wait_btn.config(state=tk.DISABLED)
        self.connect_btn.config(state=tk.DISABLED)
        self._set_status("待機中...", DARK["warn"])
        threading.Thread(target=self._server_thread, daemon=True).start()

    def _server_thread(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("", PORT))
            self.server_socket.listen(1)
            self.root.after(0, self._log,
                f"待機中です（自分のIP: {self._my_ip}）")
            conn, addr = self.server_socket.accept()
            self.conn = conn
            self.root.after(0, self._log, f"接続されました ({addr[0]})")
            self._set_connected(addr[0])
            self._receive_loop()
        except Exception as e:
            self.root.after(0, self._log, f"サーバーエラー: {e}")

    # ================================================================ クライアント接続

    def _connect(self):
        ip = self._selected_ip()
        if not ip:
            self._log("相手が見つかりません。リストから選ぶか、手動でIPを入力してください。")
            return
        self._cleanup_connection()
        self.connect_btn.config(state=tk.DISABLED)
        self.wait_btn.config(state=tk.DISABLED)
        self._set_status("接続中...", DARK["warn"])
        threading.Thread(target=self._connect_thread, args=(ip,), daemon=True).start()

    def _connect_thread(self, ip):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, PORT))
            self.conn = sock
            self.root.after(0, self._log, f"接続しました ({ip})")
            self._set_connected(ip)
            self._receive_loop()
        except Exception as e:
            self.root.after(0, self._log, f"接続できませんでした: {e}")
            self.root.after(0, self._set_status, "未接続", DARK["err"])
            self.root.after(0, self.connect_btn.config, {"state": tk.NORMAL})
            self.root.after(0, self.wait_btn.config,    {"state": tk.NORMAL})

    # ================================================================ 受信ループ

    def _receive_loop(self):
        while True:
            try:
                type_byte = self._recv_exact(1)
                if not type_byte:
                    break

                if type_byte == MSG_TYPE:
                    length = struct.unpack(">I", self._recv_exact(4))[0]
                    text = self._recv_exact(length).decode("utf-8")
                    self.root.after(0, self._log, f"相手: {text}", "peer")

                elif type_byte == FILE_TYPE:
                    fname_len = struct.unpack(">H", self._recv_exact(2))[0]
                    filename  = self._recv_exact(fname_len).decode("utf-8")
                    filesize  = struct.unpack(">Q", self._recv_exact(8))[0]
                    self.root.after(0, self._log,
                        f"ファイル受信中: {filename}  ({self._human_size(filesize)})")

                    # 一時ファイルに保存
                    suffix = os.path.splitext(filename)[1]
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp_path = tmp.name
                    tmp.close()

                    received = 0
                    with open(tmp_path, "wb") as f:
                        while received < filesize:
                            chunk = self._recv_exact(
                                min(CHUNK_SIZE, filesize - received))
                            if not chunk:
                                break
                            f.write(chunk)
                            received += len(chunk)
                            pct = received / filesize * 100
                            self.root.after(0, self._update_progress,
                                            pct, filename, received, filesize)

                    self.root.after(0, self._log_file_received,
                                    filename, tmp_path, filesize)
                    self.root.after(0, self._reset_progress)

            except Exception as e:
                self.root.after(0, self._log, f"接続が切れました: {e}")
                self.root.after(0, self._on_disconnected)
                break

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.conn.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    # ================================================================ 送信

    def _send_message(self):
        if not self.conn:
            self._log("まだ接続されていません")
            return
        text = self.msg_entry.get().strip()
        if not text:
            return
        try:
            encoded = text.encode("utf-8")
            self.conn.sendall(MSG_TYPE + struct.pack(">I", len(encoded)) + encoded)
            self._log(f"自分: {text}", "self")
            self.msg_entry.delete(0, tk.END)
        except Exception as e:
            self._log(f"送信失敗: {e}")

    def _send_file_thread(self, filepath):
        try:
            filename    = os.path.basename(filepath)
            filesize    = os.path.getsize(filepath)
            fname_bytes = filename.encode("utf-8")
            self.root.after(0, self._log,
                f"ファイル送信開始: {filename}  ({self._human_size(filesize)})")

            header = (FILE_TYPE
                      + struct.pack(">H", len(fname_bytes)) + fname_bytes
                      + struct.pack(">Q", filesize))
            self.conn.sendall(header)

            sent = 0
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.conn.sendall(chunk)
                    sent += len(chunk)
                    pct = sent / filesize * 100
                    self.root.after(0, self._update_progress,
                                    pct, filename, sent, filesize)

            self.root.after(0, self._log, f"送信完了: {filename}")
            self.root.after(0, self._reset_progress)
        except Exception as e:
            self.root.after(0, self._log, f"ファイル送信失敗: {e}")
            self.root.after(0, self._reset_progress)

    # ================================================================ ユーティリティ

    def _update_progress(self, pct, filename, done, total):
        self.progress_var.set(pct)
        self.progress_label.config(
            text=f"{filename}  {self._human_size(done)} / {self._human_size(total)}"
                 f"  ({pct:.1f}%)"
        )

    def _reset_progress(self):
        self.progress_var.set(0)
        self.progress_label.config(text="")

    @staticmethod
    def _human_size(size):
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @staticmethod
    def _get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = TkinterDnD.Tk()

    try:
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if os.path.exists(icon_path):
            icon_img = tk.PhotoImage(file=icon_path)
            root.iconphoto(True, icon_img)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
            if os.path.exists(ico_path):
                root.iconbitmap(ico_path)
        except Exception:
            pass

    app = P2PApp(root)
    root.mainloop()
