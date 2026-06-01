import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import socket
import threading
import struct
import os
import sys
import time

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
    "bg":          "#1e1e2e",   # ウィンドウ背景
    "panel":       "#2a2a3e",   # フレーム背景
    "border":      "#44475a",   # 枠線
    "input_bg":    "#313244",   # 入力欄背景
    "text":        "#cdd6f4",   # 通常テキスト
    "text_dim":    "#6c7086",   # 薄いテキスト
    "self_msg":    "#89b4fa",   # 自分のメッセージ（青）
    "peer_msg":    "#a6e3a1",   # 相手のメッセージ（緑）
    "system_msg":  "#585b70",   # システムメッセージ
    "btn_bg":      "#45475a",   # ボタン背景
    "btn_fg":      "#cdd6f4",   # ボタン文字
    "btn_active":  "#585b70",   # ボタンホバー
    "accent":      "#89b4fa",   # アクセント（接続ボタン）
    "accent_fg":   "#1e1e2e",   # アクセントボタン文字
    "ok":          "#a6e3a1",   # 緑（接続済み）
    "warn":        "#fab387",   # オレンジ（待機中）
    "err":         "#f38ba8",   # 赤（エラー）
}


class RoundedButton(tk.Canvas):
    """Canvas で描く角丸ボタン"""

    def __init__(self, parent, text, command, accent=False,
                 width=None, height=32, radius=10, **kw):
        bg_parent = parent.cget("bg")
        # width 未指定なら文字数から自動計算（日本語1文字≒14px、余白40px）
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
        self.bind("<Enter>",        self._on_enter)
        self.bind("<Leave>",        self._on_leave)
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
        fg = self._color_dis if self._disabled else self._color_fg
        self.create_text(w//2, h//2, text=self._text, fill=fg,
                         font=FONT_CHAT)

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

    def config(self, **kw):
        if "state" in kw:
            self._disabled = (kw["state"] == tk.DISABLED)
            fill = self._color_dis if self._disabled else self._color_normal
            self._draw(fill)
        else:
            super().config(**kw)

    # tk.Button 互換
    def configure(self, **kw):
        self.config(**kw)


class P2PApp:
    def __init__(self, root):
        self.root = root
        self.root.title("P2P チャット")
        self.root.geometry("520x650")
        self.root.resizable(True, True)
        self.root.configure(bg=DARK["bg"])

        self.conn = None
        self.server_socket = None
        self._peers = {}        # ip -> (hostname, last_seen)
        self._my_ip = self._get_local_ip()

        self._apply_ttk_style()
        self._build_ui()
        self._start_discovery()

    def _apply_ttk_style(self):
        style = ttk.Style()
        style.theme_use("default")
        # Progressbar
        style.configure("dark.Horizontal.TProgressbar",
            troughcolor=DARK["panel"],
            background=DARK["accent"],
            bordercolor=DARK["border"],
            lightcolor=DARK["accent"],
            darkcolor=DARK["accent"],
        )

    # ================================================================ UI

    def _btn(self, parent, text, command, accent=False, **kw):
        """角丸ボタン（Canvas 自作・幅はテキストから自動計算）"""
        return RoundedButton(parent, text=text, command=command,
                             accent=accent, height=32)

    def _label(self, parent, text, dim=False, **kw):
        fg = DARK["text_dim"] if dim else DARK["text"]
        return tk.Label(parent, text=text,
                        bg=parent["bg"], fg=fg, **kw)

    def _build_ui(self):
        D = DARK  # 短縮

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

        # 検出リスト行
        list_row = frame(conn_frame)
        list_row.pack(fill=tk.X)

        self._label(list_row, "検出された相手:").pack(side=tk.LEFT)

        # ドロップダウンメニュー（Menubutton でダーク統一）
        self.peer_var = tk.StringVar(value="（未検出）")
        self._peer_menu_obj = tk.Menu(list_row, tearoff=0,
                                      bg=DARK["input_bg"], fg=DARK["text"],
                                      activebackground=DARK["accent"],
                                      activeforeground=DARK["accent_fg"],
                                      bd=0)
        self.peer_combo = tk.Menubutton(
            list_row, textvariable=self.peer_var,
            menu=self._peer_menu_obj,
            bg=DARK["input_bg"], fg=DARK["text"],
            activebackground=DARK["border"], activeforeground=DARK["text"],
            relief=tk.FLAT,
            highlightthickness=1, highlightbackground=DARK["border"],
            width=24, anchor=tk.W, padx=6,
        )
        self.peer_combo.pack(side=tk.LEFT, padx=4)

        self._btn(list_row, "↺ 更新", self._refresh_peers).pack(side=tk.LEFT)

        # 手動IP行
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

        # ボタン行
        btn_row = frame(conn_frame)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        self.connect_btn = self._btn(btn_row, "接続する", self._connect,
                                     accent=True, width=10)
        self.connect_btn.pack(side=tk.LEFT)

        self._label(btn_row, "または", dim=True).pack(side=tk.LEFT, padx=10)

        self.wait_btn = self._btn(btn_row, "待機する", self._start_server, width=10)
        self.wait_btn.pack(side=tk.LEFT)

        self.status_label = tk.Label(conn_frame, text="● 未接続",
                                     bg=D["panel"], fg=D["text_dim"])
        self.status_label.pack(anchor=tk.W, pady=(6, 0))

        # --- チャットエリア ---
        self.chat_area = scrolledtext.ScrolledText(
            self.root, state=tk.DISABLED, wrap=tk.WORD,
            height=14, padx=8, pady=6, font=FONT_CHAT,
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

        # --- 入力エリア ---
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
        self.send_btn.grid(row=0, column=1)

        self.file_btn = self._btn(self.root, "📎  ファイルを送る", self._send_file)
        self.file_btn.pack(pady=(0, 12))

    # ================================================================ ログ

    def _log(self, text, tag="system"):
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, text + "\n", tag)
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)

    def _set_status(self, text, color=None):
        fg = color or DARK["text"]
        self.status_label.config(text=f"● {text}", fg=fg)

    def _set_connected(self, ip):
        self.root.after(0, self._set_status, f"接続中: {ip}", DARK["ok"])
        self.root.after(0, self.connect_btn.config, {"state": tk.DISABLED})
        self.root.after(0, self.wait_btn.config,    {"state": tk.DISABLED})

    # ================================================================ 自動検出

    def _start_discovery(self):
        threading.Thread(target=self._broadcast_loop,  daemon=True).start()
        threading.Thread(target=self._discovery_listen, daemon=True).start()
        self._cleanup_peers()

    def _broadcast_loop(self):
        """2秒ごとに自分の存在をブロードキャスト"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        hostname = socket.gethostname().encode("utf-8")
        payload = DISC_MSG + b"|" + hostname
        while True:
            try:
                sock.sendto(payload, ("255.255.255.255", DISC_PORT))
            except Exception:
                pass
            time.sleep(2)

    def _discovery_listen(self):
        """他のインスタンスのブロードキャストを受信"""
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
                    continue        # 自分自身は無視
                hostname = data[len(DISC_MSG) + 1:].decode("utf-8", errors="replace")
                self._peers[ip] = (hostname, time.time())
                self.root.after(0, self._refresh_peers)
            except Exception:
                pass

    def _cleanup_peers(self):
        """10秒以上応答がない相手をリストから除去"""
        now = time.time()
        expired = [ip for ip, (_, t) in self._peers.items() if now - t > 10]
        for ip in expired:
            del self._peers[ip]
        self._refresh_peers()
        self.root.after(6000, self._cleanup_peers)

    def _refresh_peers(self):
        entries = [f"{hostname}  ({ip})"
                   for ip, (hostname, _) in self._peers.items()]
        self._peer_menu_obj.delete(0, tk.END)
        if entries:
            for entry in entries:
                self._peer_menu_obj.add_command(
                    label=entry,
                    command=lambda v=entry: self.peer_var.set(v))
            if self.peer_var.get() not in entries:
                self.peer_var.set(entries[0])
        else:
            self.peer_var.set("（未検出）")

    def _selected_ip(self):
        # 手動入力を優先
        manual = self.ip_entry.get().strip()
        if manual:
            return manual
        val = self.peer_var.get()
        if not val:
            return None
        # "hostname  (192.168.x.x)" から IP を取り出す
        return val.rsplit("(", 1)[-1].rstrip(")")

    # ================================================================ サーバー待機

    def _start_server(self):
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
                        f"ファイル受信開始: {filename}  ({self._human_size(filesize)})")

                    save_path = self._safe_save_path(
                        os.path.join(DOWNLOADS, filename))

                    received = 0
                    with open(save_path, "wb") as f:
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

                    self.root.after(0, self._log, f"受信完了 → {save_path}")
                    self.root.after(0, self._reset_progress)

            except Exception as e:
                self.root.after(0, self._log, f"接続が切れました: {e}")
                self.root.after(0, self._set_status, "切断", DARK["err"])
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

    def _send_file(self):
        if not self.conn:
            self._log("まだ接続されていません")
            return
        filepath = filedialog.askopenfilename(title="送るファイルを選んでください")
        if not filepath:
            return
        threading.Thread(target=self._send_file_thread,
                         args=(filepath,), daemon=True).start()

    def _send_file_thread(self, filepath):
        try:
            filename   = os.path.basename(filepath)
            filesize   = os.path.getsize(filepath)
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

    @staticmethod
    def _safe_save_path(path):
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        i = 1
        while True:
            candidate = f"{base}_{i}{ext}"
            if not os.path.exists(candidate):
                return candidate
            i += 1


if __name__ == "__main__":
    import sys
    # Windows: 高DPI対応（ぼやけ防止）
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()

    # ウィンドウアイコン設定
    try:
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if os.path.exists(icon_path):
            icon_img = tk.PhotoImage(file=icon_path)
            root.iconphoto(True, icon_img)
    except Exception:
        pass

    # Windows: タスクバーアイコンも icon.ico に差し替え
    if sys.platform == "win32":
        try:
            ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
            if os.path.exists(ico_path):
                root.iconbitmap(ico_path)
        except Exception:
            pass

    app = P2PApp(root)
    root.mainloop()
