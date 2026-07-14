"""Modern CustomTkinter UI shell for the Grok registration application."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from proxy_pool import ProxyPoolManager, normalize_proxy_entries, parse_proxy_text, redact_proxy_url


COLORS = {
    "bg": "#F3F6FA",
    "surface": "#FFFFFF",
    "sidebar": "#F8FAFD",
    "border": "#E3E9F2",
    "text": "#172033",
    "muted": "#718096",
    "primary": "#315CF5",
    "primary_hover": "#254BD4",
    "primary_soft": "#EAF0FF",
    "success": "#178353",
    "success_soft": "#EAF9F1",
    "warning": "#B7791F",
    "warning_soft": "#FFF7E6",
    "danger": "#D64545",
    "danger_soft": "#FFF0F0",
    "log": "#172033",
    "log_text": "#CDE7D6",
}

FONT = "Microsoft YaHei UI"


def create_root():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    return ctk.CTk(fg_color=COLORS["bg"])


class ModernUIBuilder:
    """UI-only mixin. The host class supplies task callbacks and state methods."""

    nav_items = (
        ("overview", "概览", "总览运行状态与快捷操作"),
        ("registration", "注册任务", "注册数量、浏览器与代理"),
        ("proxy", "代理池", "任务级固定出口与故障切换"),
        ("email", "邮箱配置", "邮箱服务商与凭证"),
        ("cpa", "CPA 与 Token", "账号导出与令牌池"),
        ("settings", "系统设置", "低频配置与保存"),
    )

    def setup_ui(self):
        cfg = self.app_config
        self.root.title("Grok Account Studio")
        self.root.geometry("1240x820")
        self.root.minsize(1020, 700)
        self.root.configure(fg_color=COLORS["bg"])

        self._init_variables(cfg)
        self._nav_buttons = {}
        self._pages = {}

        self.shell = ctk.CTkFrame(self.root, fg_color=COLORS["bg"], corner_radius=0)
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_columnconfigure(1, weight=1)
        self.shell.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_workspace()
        self._show_page("overview")
        self._update_provider_ui(self.email_provider_var.get())
        self._refresh_outlook_summary()
        self.log("[*] 现代化 GUI 已就绪，配置已加载")
        self.log(f"[*] 当前邮箱服务商: {self.email_provider_var.get()} | 注册数量: {self.count_var.get()}")

    def _init_variables(self, cfg):
        self.email_provider_var = tk.StringVar(value=cfg.get("email_provider", "duckmail"))
        self.count_var = tk.StringVar(value=str(cfg.get("register_count", 1)))
        self.concurrency_var = tk.StringVar(value=str(cfg.get("concurrency", 1)))
        self.nsfw_var = tk.BooleanVar(value=cfg.get("enable_nsfw", True))
        self.minimized_var = tk.BooleanVar(value=cfg.get("browser_minimized", False))
        self.headless_var = tk.BooleanVar(value=cfg.get("browser_headless", False))
        self.turnstile_auto_skip_var = tk.BooleanVar(value=cfg.get("turnstile_auto_skip", True))
        self.proxy_var = tk.StringVar(value=cfg.get("proxy", ""))
        try:
            self.proxy_pool_items = normalize_proxy_entries(cfg.get("proxy_pool") or [])
        except Exception:
            self.proxy_pool_items = []
        self.proxy_pool_selected_var = tk.StringVar(value=str(cfg.get("proxy_pool_selected", "")))
        self.proxy_new_var = tk.StringVar(value="")
        self.proxy_pool_summary_var = tk.StringVar(value="代理池为空时使用注册页中的单代理配置")
        self._proxy_runtime_states = {}
        self.api_key_var = tk.StringVar(value=cfg.get("duckmail_api_key", ""))
        self.gptmail_api_key_var = tk.StringVar(value=cfg.get("gptmail_api_key", ""))
        self.cloudflare_auth_mode_var = tk.StringVar(value=cfg.get("cloudflare_auth_mode", "none"))
        self.cloudflare_api_base_var = tk.StringVar(value=cfg.get("cloudflare_api_base", ""))
        self.cloudflare_api_key_var = tk.StringVar(value=cfg.get("cloudflare_api_key", ""))
        self.cloudflare_paths_var = tk.StringVar(value=",".join([
            cfg.get("cloudflare_path_domains", "/api/domains"),
            cfg.get("cloudflare_path_accounts", "/api/new_address"),
            cfg.get("cloudflare_path_token", "/api/token"),
            cfg.get("cloudflare_path_messages", "/api/mails"),
        ]))
        self.outlook_credentials_file_var = tk.StringVar(value=str(cfg.get("outlook_credentials_file", "")))
        self.grok2api_local_auto_var = tk.BooleanVar(value=bool(cfg.get("grok2api_auto_add_local", True)))
        self.grok2api_local_file_var = tk.StringVar(value=str(cfg.get("grok2api_local_token_file", "")))
        self.grok2api_pool_name_var = tk.StringVar(value=str(cfg.get("grok2api_pool_name", "ssoBasic")))
        self.grok2api_remote_auto_var = tk.BooleanVar(value=bool(cfg.get("grok2api_auto_add_remote", False)))
        self.grok2api_remote_base_var = tk.StringVar(value=str(cfg.get("grok2api_remote_base", "")))
        self.grok2api_remote_key_var = tk.StringVar(value=str(cfg.get("grok2api_remote_app_key", "")))
        self.cpa_export_enabled_var = tk.BooleanVar(value=bool(cfg.get("cpa_export_enabled", True)))
        self.cpa_auth_dir_var = tk.StringVar(value=str(cfg.get("cpa_auth_dir", "cpa_auths")))
        self.cpa_proxy_var = tk.StringVar(value=str(cfg.get("cpa_proxy", "")))
        self.cpa_probe_after_write_var = tk.BooleanVar(value=bool(cfg.get("cpa_probe_after_write", True)))
        self.cpa_hotload_dir_var = tk.StringVar(value=str(cfg.get("cpa_hotload_dir", "")))
        self.cpa_copy_to_hotload_var = tk.BooleanVar(value=bool(cfg.get("cpa_copy_to_hotload", False)))
        self.status_var = tk.StringVar(value="就绪")
        self.stats_var = tk.StringVar(value="成功: 0 | 失败: 0")
        self.success_metric_var = tk.StringVar(value="0")
        self.fail_metric_var = tk.StringVar(value="0")
        self.target_metric_var = tk.StringVar(value=self.count_var.get())
        self.outlook_metric_var = tk.StringVar(value="—")
        self.provider_display_var = tk.StringVar(value=self.email_provider_var.get())
        self.outlook_summary_var = tk.StringVar(value="选择凭证文件后显示账号状态")
        self.save_feedback_var = tk.StringVar(value="配置修改会在启动任务时自动保存")
        self.email_provider_var.trace_add("write", lambda *_: self._update_provider_ui(self.email_provider_var.get()))
        self.outlook_credentials_file_var.trace_add("write", lambda *_: self._refresh_outlook_summary())
        self.count_var.trace_add("write", lambda *_: self.target_metric_var.set(self.count_var.get() or "0"))
        self.minimized_var.trace_add("write", lambda *_: self._refresh_browser_mode())
        self.headless_var.trace_add("write", lambda *_: self._refresh_browser_mode())

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(
            self.shell, width=214, fg_color=COLORS["sidebar"], corner_radius=0,
            border_width=1, border_color=COLORS["border"],
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(8, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=18, pady=(24, 25), sticky="ew")
        mark = ctk.CTkLabel(
            brand, text="G", width=38, height=38, corner_radius=11,
            fg_color=COLORS["primary"], text_color="white", font=(FONT, 19, "bold"),
        )
        mark.pack(side="left")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(brand_text, text="Grok Studio", text_color=COLORS["text"], font=(FONT, 15, "bold")).pack(anchor="w")
        ctk.CTkLabel(brand_text, text="Registration Console", text_color=COLORS["muted"], font=(FONT, 9)).pack(anchor="w")

        for index, (key, label, _) in enumerate(self.nav_items, start=1):
            button = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=42, corner_radius=10,
                fg_color="transparent", hover_color=COLORS["primary_soft"],
                text_color=COLORS["muted"], font=(FONT, 13),
                command=lambda page=key: self._show_page(page),
            )
            button.grid(row=index, column=0, padx=14, pady=3, sticky="ew")
            self._nav_buttons[key] = button

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=9, column=0, padx=16, pady=18, sticky="sew")
        ctk.CTkLabel(footer, text="LOCAL AUTOMATION", text_color="#A0AABC", font=(FONT, 9, "bold")).pack(anchor="w")
        ctk.CTkLabel(footer, text="配置与凭证仅保存在本地", text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", pady=(3, 0))

    def _build_workspace(self):
        workspace = ctk.CTkFrame(self.shell, fg_color=COLORS["bg"], corner_radius=0)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.grid_columnconfigure(0, weight=1)
        workspace.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(workspace, fg_color="transparent", height=94)
        header.grid(row=0, column=0, padx=28, pady=(18, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        self.page_title_label = ctk.CTkLabel(header, text="概览", text_color=COLORS["text"], font=(FONT, 25, "bold"))
        self.page_title_label.grid(row=0, column=0, sticky="w")
        self.page_subtitle_label = ctk.CTkLabel(header, text="总览运行状态与快捷操作", text_color=COLORS["muted"], font=(FONT, 11))
        self.page_subtitle_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        provider_pill = ctk.CTkFrame(header, fg_color=COLORS["surface"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        provider_pill.grid(row=0, column=1, rowspan=2, padx=(12, 8), sticky="e")
        ctk.CTkLabel(provider_pill, text="邮箱", text_color=COLORS["muted"], font=(FONT, 10)).pack(side="left", padx=(12, 5), pady=8)
        ctk.CTkLabel(provider_pill, textvariable=self.provider_display_var, text_color=COLORS["text"], font=(FONT, 11, "bold")).pack(side="left", padx=(0, 12), pady=8)
        self.status_label = ctk.CTkLabel(
            header, textvariable=self.status_var, text_color=COLORS["success"],
            fg_color=COLORS["success_soft"], corner_radius=12, font=(FONT, 11, "bold"),
            width=86, height=34,
        )
        self.status_label.grid(row=0, column=2, rowspan=2, sticky="e")

        self.page_host = ctk.CTkFrame(workspace, fg_color="transparent")
        self.page_host.grid(row=1, column=0, padx=28, pady=(0, 24), sticky="nsew")
        self.page_host.grid_columnconfigure(0, weight=1)
        self.page_host.grid_rowconfigure(0, weight=1)

        self._pages["overview"] = self._build_overview_page()
        self._pages["registration"] = self._build_registration_page()
        self._pages["proxy"] = self._build_proxy_page()
        self._pages["email"] = self._build_email_page()
        self._pages["cpa"] = self._build_cpa_page()
        self._pages["settings"] = self._build_settings_page()

    def _page(self):
        page = ctk.CTkScrollableFrame(self.page_host, fg_color="transparent", corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        return page

    def _card(self, parent, title=None, subtitle=None):
        card = ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        if title:
            ctk.CTkLabel(card, text=title, text_color=COLORS["text"], font=(FONT, 14, "bold")).pack(anchor="w", padx=18, pady=(16, 1))
            if subtitle:
                ctk.CTkLabel(card, text=subtitle, text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", padx=18, pady=(0, 10))
        return card

    def _metric_card(self, parent, title, variable, accent):
        card = self._card(parent)
        ctk.CTkLabel(card, text=title, text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", padx=16, pady=(14, 1))
        ctk.CTkLabel(card, textvariable=variable, text_color=COLORS["text"], font=(FONT, 25, "bold")).pack(anchor="w", padx=16)
        ctk.CTkFrame(card, height=4, fg_color=accent, corner_radius=2).pack(fill="x", padx=16, pady=(10, 14))
        return card

    def _field(self, parent, label, variable, secret=False, placeholder=""):
        holder = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(holder, text=label, text_color=COLORS["text"], font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 5))
        entry = ctk.CTkEntry(
            holder, textvariable=variable, height=38, corner_radius=9,
            fg_color="#FAFBFD", border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text"], placeholder_text=placeholder,
            show="•" if secret else "",
        )
        entry.pack(fill="x")
        return holder, entry

    def _switch(self, parent, text, variable):
        return ctk.CTkSwitch(
            parent, text=text, variable=variable, progress_color=COLORS["primary"],
            button_color="white", button_hover_color="#EDF1F7", text_color=COLORS["text"], font=(FONT, 11),
        )

    def _primary_button(self, parent, text, command):
        return ctk.CTkButton(
            parent, text=text, command=command, height=40, corner_radius=9,
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"], font=(FONT, 12, "bold"),
        )

    def _build_overview_page(self):
        page = self._page()
        metrics = ctk.CTkFrame(page, fg_color="transparent")
        metrics.pack(fill="x")
        for i in range(4):
            metrics.grid_columnconfigure(i, weight=1)
        cards = (
            ("本次目标", self.target_metric_var, COLORS["primary"]),
            ("注册成功", self.success_metric_var, COLORS["success"]),
            ("注册失败", self.fail_metric_var, COLORS["danger"]),
            ("Outlook 可用", self.outlook_metric_var, "#7B61FF"),
        )
        for col, args in enumerate(cards):
            self._metric_card(metrics, *args).grid(row=0, column=col, padx=(0 if col == 0 else 6, 0 if col == 3 else 6), sticky="ew")

        middle = ctk.CTkFrame(page, fg_color="transparent")
        middle.pack(fill="x", pady=14)
        middle.grid_columnconfigure(0, weight=3)
        middle.grid_columnconfigure(1, weight=2)
        quick = self._card(middle, "快速启动", "调整常用参数后即可开始任务")
        quick.grid(row=0, column=0, padx=(0, 7), sticky="nsew")
        qbody = ctk.CTkFrame(quick, fg_color="transparent")
        qbody.pack(fill="x", padx=18, pady=(2, 18))
        qbody.grid_columnconfigure((0, 1), weight=1)
        _, self.overview_count_entry = self._field(qbody, "注册数量", self.count_var)
        self.overview_count_entry.master.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        provider = ctk.CTkFrame(qbody, fg_color="transparent")
        ctk.CTkLabel(provider, text="邮箱服务商", text_color=COLORS["text"], font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 5))
        ctk.CTkOptionMenu(provider, variable=self.email_provider_var, values=["duckmail", "yyds", "cloudflare", "gptmail", "outlook"], height=38, fg_color="#FAFBFD", button_color=COLORS["primary"], text_color=COLORS["text"], dropdown_fg_color="white", dropdown_text_color=COLORS["text"]).pack(fill="x")
        provider.grid(row=0, column=1, padx=(6, 0), sticky="ew")
        actions = ctk.CTkFrame(qbody, fg_color="transparent")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.start_btn = self._primary_button(actions, "开始注册", self.start_registration)
        self.start_btn.pack(side="left")
        self.stop_btn = ctk.CTkButton(actions, text="停止任务", command=self.stop_registration, state="disabled", height=40, corner_radius=9, fg_color=COLORS["danger_soft"], hover_color="#FFE2E2", text_color=COLORS["danger"], font=(FONT, 12, "bold"))
        self.stop_btn.pack(side="left", padx=8)

        resource = self._card(middle, "当前配置", "任务启动前的关键资源状态")
        resource.grid(row=0, column=1, padx=(7, 0), sticky="nsew")
        self.resource_provider_label = ctk.CTkLabel(resource, text="邮箱服务商", text_color=COLORS["muted"], font=(FONT, 10))
        self.resource_provider_label.pack(anchor="w", padx=18, pady=(4, 0))
        ctk.CTkLabel(resource, textvariable=self.provider_display_var, text_color=COLORS["text"], font=(FONT, 15, "bold")).pack(anchor="w", padx=18)
        ctk.CTkLabel(resource, text="浏览器模式", text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", padx=18, pady=(12, 0))
        self.browser_mode_var = tk.StringVar(value="标准窗口")
        ctk.CTkLabel(resource, textvariable=self.browser_mode_var, text_color=COLORS["text"], font=(FONT, 13, "bold")).pack(anchor="w", padx=18)
        ctk.CTkLabel(resource, textvariable=self.outlook_summary_var, wraplength=260, justify="left", text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", padx=18, pady=(14, 18))
        self._refresh_browser_mode()

        log_card = self._card(page, "实时日志", "任务状态、验证码和导出结果会显示在这里")
        log_card.pack(fill="both", expand=True)
        toolbar = ctk.CTkFrame(log_card, fg_color="transparent")
        toolbar.pack(fill="x", padx=18, pady=(0, 8))
        self.clear_btn = ctk.CTkButton(toolbar, text="清空日志", command=self.clear_log, width=88, height=30, corner_radius=8, fg_color=COLORS["primary_soft"], hover_color="#DDE6FF", text_color=COLORS["primary"], font=(FONT, 10, "bold"))
        self.clear_btn.pack(side="right")
        self.log_text = ctk.CTkTextbox(log_card, height=245, corner_radius=10, fg_color=COLORS["log"], text_color=COLORS["log_text"], border_width=0, font=("Cascadia Mono", 11), wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        return page

    def _build_registration_page(self):
        page = self._page()
        card = self._card(page, "任务参数", "控制注册批次、浏览器运行方式和网络出口")
        card.pack(fill="x")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(5, 18))
        body.grid_columnconfigure((0, 1), weight=1)
        f1, self.count_spinbox = self._field(body, "注册数量", self.count_var, placeholder="1")
        f1.grid(row=0, column=0, padx=(0, 7), sticky="ew")
        f2, self.concurrency_spinbox = self._field(body, "并发数", self.concurrency_var, placeholder="1")
        f2.grid(row=0, column=1, padx=(7, 0), sticky="ew")
        f3, self.proxy_entry = self._field(body, "单代理（代理池为空时使用）", self.proxy_var, placeholder="http://127.0.0.1:7890")
        f3.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ctk.CTkLabel(
            body,
            textvariable=self.proxy_pool_summary_var,
            text_color=COLORS["muted"],
            fg_color=COLORS["bg"],
            corner_radius=8,
            font=(FONT, 10),
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0), ipady=8)
        switches = ctk.CTkFrame(body, fg_color=COLORS["bg"], corner_radius=10)
        switches.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.nsfw_check = self._switch(switches, "注册后开启 NSFW", self.nsfw_var)
        self.nsfw_check.pack(side="left", padx=14, pady=14)
        self.minimized_check = self._switch(switches, "最小化浏览器", self.minimized_var)
        self.minimized_check.pack(side="left", padx=14, pady=14)
        self.headless_check = self._switch(switches, "无头模式（受拦截时自动最小化）", self.headless_var)
        self.headless_check.pack(side="left", padx=14, pady=14)
        self.turnstile_auto_skip_check = self._switch(
            body,
            "遇到人机验证自动跳过（不再等待人工操作）",
            self.turnstile_auto_skip_var,
        )
        self.turnstile_auto_skip_check.grid(row=4, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ctk.CTkLabel(body, text="Outlook 邮箱模式会自动限制为单并发，避免同一邮箱重复占用。", text_color=COLORS["warning"], fg_color=COLORS["warning_soft"], corner_radius=8, font=(FONT, 10)).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(14, 0), ipady=8)
        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.pack(fill="x", pady=14)
        self.registration_start_btn = self._primary_button(actions, "保存并开始注册", self.start_registration)
        self.registration_start_btn.pack(side="left")
        self.registration_stop_btn = ctk.CTkButton(actions, text="停止", command=self.stop_registration, state="disabled", fg_color=COLORS["danger_soft"], hover_color="#FFE2E2", text_color=COLORS["danger"], height=40, corner_radius=9)
        self.registration_stop_btn.pack(side="left", padx=8)
        return page

    def _build_proxy_page(self):
        page = self._page()
        intro = self._card(page, "安全代理池", "完整注册尝试固定一个出口，仅在明确的代理连接故障后为下一次尝试切换")
        intro.pack(fill="x")
        body = ctk.CTkFrame(intro, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(4, 18))
        add_row = ctk.CTkFrame(body, fg_color="transparent")
        add_row.pack(fill="x")
        self.proxy_new_entry = ctk.CTkEntry(
            add_row,
            textvariable=self.proxy_new_var,
            height=38,
            corner_radius=9,
            fg_color="#FAFBFD",
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            placeholder_text="http://127.0.0.1:7897 或 socks5://127.0.0.1:1080",
        )
        self.proxy_new_entry.pack(side="left", fill="x", expand=True)
        self.proxy_add_btn = ctk.CTkButton(
            add_row,
            text="添加",
            command=self._add_proxy_from_entry,
            width=82,
            height=38,
            corner_radius=9,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
        )
        self.proxy_add_btn.pack(side="left", padx=(8, 0))

        toolbar = ctk.CTkFrame(body, fg_color="transparent")
        toolbar.pack(fill="x", pady=(12, 0))
        self.proxy_import_btn = ctk.CTkButton(toolbar, text="导入 TXT", command=self._import_proxy_file, width=94, height=34, corner_radius=8, fg_color=COLORS["primary_soft"], hover_color="#DDE6FF", text_color=COLORS["primary"])
        self.proxy_import_btn.pack(side="left")
        self.proxy_check_btn = ctk.CTkButton(toolbar, text="检测全部", command=self._check_proxy_pool, width=94, height=34, corner_radius=8, fg_color=COLORS["primary_soft"], hover_color="#DDE6FF", text_color=COLORS["primary"])
        self.proxy_check_btn.pack(side="left", padx=8)
        self.proxy_save_btn = ctk.CTkButton(toolbar, text="保存代理池", command=self._save_proxy_pool, width=104, height=34, corner_radius=8, fg_color=COLORS["success_soft"], hover_color="#DFF5E9", text_color=COLORS["success"])
        self.proxy_save_btn.pack(side="left")
        ctk.CTkLabel(toolbar, text="不解析订阅链接；Clash/V2Ray 请填写本地 HTTP/SOCKS5 端口", text_color=COLORS["muted"], font=(FONT, 9)).pack(side="right")

        list_card = self._card(page, "代理列表", "选择“优先”后，任务会优先使用该代理；所有代理不可用时不会回退直连")
        list_card.pack(fill="both", expand=True, pady=14)
        self.proxy_rows_host = ctk.CTkScrollableFrame(list_card, fg_color="transparent", height=340, corner_radius=0)
        self.proxy_rows_host.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._refresh_proxy_rows()
        return page

    def _merge_proxy_entries(self, entries):
        existing = {item["url"] for item in self.proxy_pool_items}
        added = 0
        for entry in entries:
            if entry["url"] not in existing:
                self.proxy_pool_items.append(entry)
                existing.add(entry["url"])
                added += 1
        self._refresh_proxy_rows()
        self.proxy_pool_summary_var.set(f"代理池共 {len(self.proxy_pool_items)} 个，新增 {added} 个")

    def _add_proxy_from_entry(self):
        try:
            entries = parse_proxy_text(self.proxy_new_var.get())
            if not entries:
                raise ValueError("请输入代理地址")
            self._merge_proxy_entries(entries)
            self.proxy_new_var.set("")
        except Exception as exc:
            self.proxy_pool_summary_var.set(f"添加失败：{exc}")

    def _import_proxy_file(self):
        path = filedialog.askopenfilename(title="导入代理 TXT", filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            if os.path.getsize(path) > 1024 * 1024:
                raise ValueError("代理文件不能超过 1MB")
            with open(path, "r", encoding="utf-8-sig") as handle:
                entries = parse_proxy_text(handle.read())
            self._merge_proxy_entries(entries)
        except Exception as exc:
            self.proxy_pool_summary_var.set(f"导入失败：{exc}")

    def _set_proxy_enabled(self, index, variable):
        if 0 <= index < len(self.proxy_pool_items):
            self.proxy_pool_items[index]["enabled"] = bool(variable.get())
            self._save_proxy_pool(silent=True)

    def _select_proxy(self, url):
        self.proxy_pool_selected_var.set(url)
        self._save_proxy_pool(silent=True)
        self._refresh_proxy_rows()

    def _delete_proxy(self, index):
        if not 0 <= index < len(self.proxy_pool_items):
            return
        removed = self.proxy_pool_items.pop(index)
        if self.proxy_pool_selected_var.get() == removed["url"]:
            self.proxy_pool_selected_var.set("")
        self._proxy_runtime_states.pop(removed["url"], None)
        self._save_proxy_pool(silent=True)
        self._refresh_proxy_rows()

    def _refresh_proxy_rows(self):
        if not hasattr(self, "proxy_rows_host"):
            return
        for child in self.proxy_rows_host.winfo_children():
            child.destroy()
        if not self.proxy_pool_items:
            ctk.CTkLabel(self.proxy_rows_host, text="暂无代理，可直接添加或导入 TXT", text_color=COLORS["muted"], font=(FONT, 11)).pack(pady=48)
            self.proxy_pool_summary_var.set("代理池为空时使用注册页中的单代理配置")
            return
        for index, item in enumerate(self.proxy_pool_items):
            row = ctk.CTkFrame(self.proxy_rows_host, fg_color=COLORS["surface"], corner_radius=11, border_width=1, border_color=COLORS["border"])
            row.pack(fill="x", pady=5)
            enabled_var = tk.BooleanVar(value=bool(item.get("enabled", True)))
            ctk.CTkSwitch(row, text="", variable=enabled_var, width=42, command=lambda i=index, v=enabled_var: self._set_proxy_enabled(i, v)).pack(side="left", padx=(12, 6), pady=12)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, pady=9)
            name = item.get("name") or f"代理 {index + 1}"
            ctk.CTkLabel(info, text=name, text_color=COLORS["text"], font=(FONT, 11, "bold")).pack(anchor="w")
            ctk.CTkLabel(info, text=redact_proxy_url(item["url"]), text_color=COLORS["muted"], font=("Cascadia Mono", 9)).pack(anchor="w", pady=(2, 0))
            state = self._proxy_runtime_states.get(item["url"])
            if state is None:
                status_text, status_color = "未检测", COLORS["muted"]
            elif getattr(state, "healthy", None) is True:
                status_text, status_color = f"可用 · {state.latency_ms}ms", COLORS["success"]
            else:
                status_text, status_color = f"不可用 · {getattr(state, 'last_error', '')[:48]}", COLORS["danger"]
            ctk.CTkLabel(row, text=status_text, text_color=status_color, font=(FONT, 9, "bold")).pack(side="left", padx=8)
            selected = self.proxy_pool_selected_var.get() == item["url"]
            ctk.CTkButton(row, text="已优先" if selected else "设为优先", command=lambda url=item["url"]: self._select_proxy(url), width=76, height=30, corner_radius=8, fg_color=COLORS["primary"] if selected else COLORS["primary_soft"], hover_color=COLORS["primary_hover"] if selected else "#DDE6FF", text_color="white" if selected else COLORS["primary"]).pack(side="left", padx=6)
            ctk.CTkButton(row, text="删除", command=lambda i=index: self._delete_proxy(i), width=58, height=30, corner_radius=8, fg_color=COLORS["danger_soft"], hover_color="#FFE2E2", text_color=COLORS["danger"]).pack(side="left", padx=(0, 10))
        selected = self.proxy_pool_selected_var.get()
        label = redact_proxy_url(selected) if selected else "自动选择可用代理"
        self.proxy_pool_summary_var.set(f"代理池 {len(self.proxy_pool_items)} 个 · {label}")

    def _save_proxy_pool(self, silent=False):
        self.app_config["proxy_pool"] = [dict(item) for item in self.proxy_pool_items]
        self.app_config["proxy_pool_selected"] = self.proxy_pool_selected_var.get().strip()
        self.save_config_callback()
        if not silent:
            self.proxy_pool_summary_var.set(f"代理池已保存，共 {len(self.proxy_pool_items)} 个")

    def _check_proxy_pool(self):
        if not self.proxy_pool_items:
            self.proxy_pool_summary_var.set("代理池为空，无法检测")
            return
        self._save_proxy_pool(silent=True)
        self.proxy_pool_summary_var.set(f"正在检测 {len(self.proxy_pool_items)} 个代理…")
        self.proxy_check_btn.configure(state="disabled", text="检测中…")

        def worker():
            manager = ProxyPoolManager.from_config(self.app_config)
            states = manager.check_all(timeout=8)
            self.ui_queue.put(("proxy_states", states))

        threading.Thread(target=worker, name="proxy-health-check", daemon=True).start()

    def _apply_proxy_states(self, states):
        self._proxy_runtime_states = states or {}
        healthy = sum(1 for state in self._proxy_runtime_states.values() if state.healthy is True)
        self.proxy_pool_summary_var.set(f"检测完成：{healthy}/{len(self.proxy_pool_items)} 个可用")
        self.proxy_check_btn.configure(state="normal", text="检测全部")
        self._refresh_proxy_rows()

    def _build_email_page(self):
        page = self._page()
        selector = self._card(page, "邮箱服务商", "切换服务商不会清空其他服务商的配置")
        selector.pack(fill="x")
        ctk.CTkOptionMenu(selector, variable=self.email_provider_var, values=["duckmail", "yyds", "cloudflare", "gptmail", "outlook"], height=40, width=260, fg_color=COLORS["primary"], button_color=COLORS["primary_hover"], dropdown_fg_color="white", dropdown_text_color=COLORS["text"], command=self._update_provider_ui).pack(anchor="w", padx=18, pady=(6, 18))
        self.email_provider_host = ctk.CTkFrame(page, fg_color="transparent")
        self.email_provider_host.pack(fill="x", pady=14)
        self._email_sections = {}

        duck = self._card(self.email_provider_host, "DuckMail", "使用 API Key 创建临时邮箱并读取验证码")
        f, self.api_key_entry = self._field(duck, "API Key", self.api_key_var, secret=True)
        f.pack(fill="x", padx=18, pady=(5, 18))
        self._email_sections["duckmail"] = duck

        gpt = self._card(self.email_provider_host, "GPTMail", "通过 GPTMail API 创建邮箱并轮询验证码")
        f, self.gptmail_api_key_entry = self._field(gpt, "API Key", self.gptmail_api_key_var, secret=True)
        f.pack(fill="x", padx=18, pady=(5, 18))
        self._email_sections["gptmail"] = gpt

        cf = self._card(self.email_provider_host, "Cloudflare 临时邮箱", "配置 Worker API、鉴权方式和接口路径")
        cfbody = ctk.CTkFrame(cf, fg_color="transparent")
        cfbody.pack(fill="x", padx=18, pady=(5, 18))
        cfbody.grid_columnconfigure((0, 1), weight=1)
        f, self.cloudflare_api_base_entry = self._field(cfbody, "API Base", self.cloudflare_api_base_var)
        f.grid(row=0, column=0, padx=(0, 7), sticky="ew")
        auth = ctk.CTkFrame(cfbody, fg_color="transparent")
        ctk.CTkLabel(auth, text="鉴权模式", text_color=COLORS["text"], font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 5))
        self.cloudflare_auth_mode_combo = ctk.CTkOptionMenu(auth, variable=self.cloudflare_auth_mode_var, values=["none", "query-key", "bearer", "x-api-key", "x-admin-auth"], height=38, fg_color="#FAFBFD", button_color=COLORS["primary"], text_color=COLORS["text"], dropdown_fg_color="white", dropdown_text_color=COLORS["text"])
        self.cloudflare_auth_mode_combo.pack(fill="x")
        auth.grid(row=0, column=1, padx=(7, 0), sticky="ew")
        f, self.cloudflare_api_key_entry = self._field(cfbody, "API Key / Admin Password", self.cloudflare_api_key_var, secret=True)
        f.grid(row=1, column=0, padx=(0, 7), pady=(14, 0), sticky="ew")
        f, self.cloudflare_paths_entry = self._field(cfbody, "接口路径（逗号分隔）", self.cloudflare_paths_var)
        f.grid(row=1, column=1, padx=(7, 0), pady=(14, 0), sticky="ew")
        self._email_sections["cloudflare"] = cf

        outlook = self._card(self.email_provider_host, "Outlook / Hotmail", "使用现有账号的 Microsoft Graph OAuth 凭证读取验证码")
        obody = ctk.CTkFrame(outlook, fg_color="transparent")
        obody.pack(fill="x", padx=18, pady=(5, 18))
        f, self.outlook_credentials_file_entry = self._field(obody, "凭证文件", self.outlook_credentials_file_var, placeholder="outlook_accounts.txt")
        f.pack(fill="x")
        ctk.CTkLabel(obody, textvariable=self.outlook_summary_var, text_color=COLORS["muted"], fg_color=COLORS["bg"], corner_radius=8, font=(FONT, 10), anchor="w").pack(fill="x", pady=(12, 0), ipady=8, padx=0)
        ctk.CTkButton(obody, text="重新检测", command=self._refresh_outlook_summary, width=96, height=32, corner_radius=8, fg_color=COLORS["primary_soft"], hover_color="#DDE6FF", text_color=COLORS["primary"]).pack(anchor="w", pady=(10, 0))
        self._email_sections["outlook"] = outlook

        yyds = self._card(self.email_provider_host, "YYDS", "YYDS 凭证继续沿用 config.json 中的现有配置")
        ctk.CTkLabel(yyds, text="当前版本暂不在 GUI 中显示敏感 YYDS 凭证，任务会继续读取已有配置。", text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", padx=18, pady=(6, 18))
        self._email_sections["yyds"] = yyds
        return page

    def _build_cpa_page(self):
        page = self._page()
        local = self._card(page, "本地 Token 池", "将注册成功的 Token 写入本机 grok2api 池")
        local.pack(fill="x")
        lbody = ctk.CTkFrame(local, fg_color="transparent")
        lbody.pack(fill="x", padx=18, pady=(5, 18))
        self.grok2api_local_auto_check = self._switch(lbody, "自动写入本地池", self.grok2api_local_auto_var)
        self.grok2api_local_auto_check.pack(anchor="w")
        f, self.grok2api_local_file_entry = self._field(lbody, "本地 token.json", self.grok2api_local_file_var)
        f.pack(fill="x", pady=(14, 0))
        pool = ctk.CTkFrame(lbody, fg_color="transparent")
        ctk.CTkLabel(pool, text="池名称", text_color=COLORS["text"], font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 5))
        self.grok2api_pool_name_combo = ctk.CTkOptionMenu(pool, variable=self.grok2api_pool_name_var, values=["ssoBasic", "ssoSuper"], height=38, fg_color="#FAFBFD", button_color=COLORS["primary"], text_color=COLORS["text"], dropdown_fg_color="white", dropdown_text_color=COLORS["text"])
        self.grok2api_pool_name_combo.pack(fill="x")
        pool.pack(fill="x", pady=(14, 0))

        remote = self._card(page, "远程 Token 池", "通过管理 API 将 Token 写入远程 grok2api")
        remote.pack(fill="x", pady=14)
        rbody = ctk.CTkFrame(remote, fg_color="transparent")
        rbody.pack(fill="x", padx=18, pady=(5, 18))
        self.grok2api_remote_auto_check = self._switch(rbody, "自动写入远程池", self.grok2api_remote_auto_var)
        self.grok2api_remote_auto_check.pack(anchor="w")
        f, self.grok2api_remote_base_entry = self._field(rbody, "远程 Base URL", self.grok2api_remote_base_var)
        f.pack(fill="x", pady=(14, 0))
        f, self.grok2api_remote_key_entry = self._field(rbody, "远程 app_key", self.grok2api_remote_key_var, secret=True)
        f.pack(fill="x", pady=(14, 0))

        cpa = self._card(page, "CPA xAI 导出", "配置认证文件生成、可用性探测和服务器热加载目录")
        cpa.pack(fill="x")
        cbody = ctk.CTkFrame(cpa, fg_color="transparent")
        cbody.pack(fill="x", padx=18, pady=(5, 18))
        self.cpa_export_enabled_check = self._switch(cbody, "注册成功后导出 CPA xAI 认证", self.cpa_export_enabled_var)
        self.cpa_export_enabled_check.pack(anchor="w")
        f, self.cpa_auth_dir_entry = self._field(cbody, "CPA 认证目录", self.cpa_auth_dir_var)
        f.pack(fill="x", pady=(14, 0))
        f, self.cpa_proxy_entry = self._field(
            cbody,
            "CPA / 账号初始化代理",
            self.cpa_proxy_var,
            placeholder="http://127.0.0.1:7897",
        )
        f.pack(fill="x", pady=(14, 0))
        self.cpa_probe_after_write_check = self._switch(cbody, "写入后检测账号可用性", self.cpa_probe_after_write_var)
        self.cpa_probe_after_write_check.pack(anchor="w", pady=(14, 0))
        f, self.cpa_hotload_dir_entry = self._field(cbody, "热加载目录（可选）", self.cpa_hotload_dir_var)
        f.pack(fill="x", pady=(14, 0))
        self.cpa_copy_to_hotload_check = self._switch(cbody, "同时复制到热加载目录", self.cpa_copy_to_hotload_var)
        self.cpa_copy_to_hotload_check.pack(anchor="w", pady=(14, 0))
        ctk.CTkLabel(cbody, text="账号文件包含敏感令牌。界面不会显示 Token 内容，导出状态会写入实时日志。", text_color=COLORS["warning"], fg_color=COLORS["warning_soft"], corner_radius=8, font=(FONT, 10)).pack(fill="x", pady=(14, 0), ipady=8)
        return page

    def _build_settings_page(self):
        page = self._page()
        card = self._card(page, "应用设置", "保存当前界面中的注册、邮箱和 Token 池配置")
        card.pack(fill="x")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(5, 18))
        ctk.CTkLabel(body, text="配置文件", text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w")
        ctk.CTkLabel(body, text=os.path.join(self.app_dir, "config.json"), text_color=COLORS["text"], font=("Cascadia Mono", 10), wraplength=720, justify="left").pack(anchor="w", pady=(2, 14))
        self.settings_save_btn = self._primary_button(body, "保存配置", self._save_settings_only)
        self.settings_save_btn.pack(anchor="w")
        ctk.CTkLabel(body, textvariable=self.save_feedback_var, text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", pady=(10, 0))
        about = self._card(page, "关于", "Grok 自动注册与 CPA 导出工作台")
        about.pack(fill="x", pady=14)
        ctk.CTkLabel(about, text="现代化 GUI 不改变 CLI 命令、配置格式或注册业务流程。", text_color=COLORS["muted"], font=(FONT, 10)).pack(anchor="w", padx=18, pady=(6, 18))
        return page

    def _show_page(self, key):
        for page in self._pages.values():
            page.grid_forget()
        page = self._pages[key]
        page.grid(row=0, column=0, sticky="nsew")
        for nav_key, button in self._nav_buttons.items():
            active = nav_key == key
            button.configure(
                fg_color=COLORS["primary_soft"] if active else "transparent",
                text_color=COLORS["primary"] if active else COLORS["muted"],
                font=(FONT, 13, "bold" if active else "normal"),
            )
        item = next(item for item in self.nav_items if item[0] == key)
        self.page_title_label.configure(text=item[1])
        self.page_subtitle_label.configure(text=item[2])

    def _update_provider_ui(self, provider):
        provider = str(provider or "duckmail")
        self.provider_display_var.set(provider)
        if hasattr(self, "_email_sections"):
            for section in self._email_sections.values():
                section.pack_forget()
            self._email_sections.get(provider, self._email_sections["duckmail"]).pack(fill="x")
        self._refresh_outlook_summary()

    def _refresh_outlook_summary(self):
        if not hasattr(self, "outlook_summary_var"):
            return
        raw = self.outlook_credentials_file_var.get().strip()
        if not raw:
            self.outlook_summary_var.set("尚未配置 Outlook 凭证文件")
            self.outlook_metric_var.set("—")
            return
        path = raw if os.path.isabs(raw) else os.path.join(self.app_dir, raw)
        try:
            pool = self.outlook_pool_loader(path)
            usable = sum(1 for account in pool.accounts if account.usable)
            self.outlook_summary_var.set(f"已导入 {len(pool.accounts)} 个账号，其中 {usable} 个 OAuth 凭证可用")
            self.outlook_metric_var.set(str(usable))
        except Exception as exc:
            self.outlook_summary_var.set(f"凭证文件不可用：{exc}")
            self.outlook_metric_var.set("0")

    def _refresh_browser_mode(self):
        if not hasattr(self, "browser_mode_var"):
            return
        if self.headless_var.get():
            mode = "无头模式（CF 时自动最小化）"
        elif self.minimized_var.get():
            mode = "最小化窗口"
        else:
            mode = "标准窗口"
        self.browser_mode_var.set(mode)

    def _save_settings_only(self):
        try:
            self.collect_ui_config()
            self.save_config_callback()
            self.save_feedback_var.set("配置已保存")
            self.log("[*] 配置已保存")
        except Exception as exc:
            self.save_feedback_var.set(f"保存失败：{exc}")

    def collect_ui_config(self):
        cfg = self.app_config
        cfg["email_provider"] = self.email_provider_var.get().strip() or "duckmail"
        cfg["enable_nsfw"] = bool(self.nsfw_var.get())
        cfg["browser_minimized"] = bool(self.minimized_var.get())
        cfg["browser_headless"] = bool(self.headless_var.get())
        cfg["turnstile_auto_skip"] = bool(self.turnstile_auto_skip_var.get())
        cfg["proxy"] = self.proxy_var.get().strip()
        cfg["proxy_pool"] = [dict(item) for item in self.proxy_pool_items]
        cfg["proxy_pool_selected"] = self.proxy_pool_selected_var.get().strip()
        cfg["duckmail_api_key"] = self.api_key_var.get().strip()
        cfg["gptmail_api_key"] = self.gptmail_api_key_var.get().strip()
        cfg["outlook_credentials_file"] = self.outlook_credentials_file_var.get().strip()
        cfg["cloudflare_api_base"] = self.cloudflare_api_base_var.get().strip()
        cfg["cloudflare_api_key"] = self.cloudflare_api_key_var.get().strip()
        cfg["cloudflare_auth_mode"] = self.cloudflare_auth_mode_var.get().strip() or "none"
        cfg["grok2api_auto_add_local"] = bool(self.grok2api_local_auto_var.get())
        cfg["grok2api_local_token_file"] = self.grok2api_local_file_var.get().strip()
        cfg["grok2api_pool_name"] = self.grok2api_pool_name_var.get().strip() or "ssoBasic"
        cfg["grok2api_auto_add_remote"] = bool(self.grok2api_remote_auto_var.get())
        cfg["grok2api_remote_base"] = self.grok2api_remote_base_var.get().strip()
        cfg["grok2api_remote_app_key"] = self.grok2api_remote_key_var.get().strip()
        cfg["cpa_export_enabled"] = bool(self.cpa_export_enabled_var.get())
        cfg["cpa_auth_dir"] = self.cpa_auth_dir_var.get().strip() or "cpa_auths"
        cfg["cpa_proxy"] = self.cpa_proxy_var.get().strip()
        cfg["cpa_probe_after_write"] = bool(self.cpa_probe_after_write_var.get())
        cfg["cpa_hotload_dir"] = self.cpa_hotload_dir_var.get().strip()
        cfg["cpa_copy_to_hotload"] = bool(self.cpa_copy_to_hotload_var.get())
        try:
            cfg["register_count"] = max(1, int(self.count_var.get()))
        except Exception:
            pass
        try:
            cfg["concurrency"] = max(1, int(self.concurrency_var.get()))
        except Exception:
            pass
        paths = [part.strip() for part in self.cloudflare_paths_var.get().split(",") if part.strip()]
        if len(paths) >= 4:
            keys = ("cloudflare_path_domains", "cloudflare_path_accounts", "cloudflare_path_token", "cloudflare_path_messages")
            for key, value in zip(keys, paths[:4]):
                cfg[key] = value if value.startswith("/") else "/" + value

    def sync_running_controls(self, running):
        state_start = "disabled" if running else "normal"
        state_stop = "normal" if running else "disabled"
        for name in ("start_btn", "registration_start_btn"):
            widget = getattr(self, name, None)
            if widget:
                widget.configure(state=state_start)
        for name in ("stop_btn", "registration_stop_btn"):
            widget = getattr(self, name, None)
            if widget:
                widget.configure(state=state_stop)
        for name in ("proxy_add_btn", "proxy_import_btn", "proxy_check_btn", "proxy_save_btn"):
            widget = getattr(self, name, None)
            if widget:
                widget.configure(state=state_start)
        self.status_label.configure(
            text_color=COLORS["primary"] if running else COLORS["success"],
            fg_color=COLORS["primary_soft"] if running else COLORS["success_soft"],
        )
