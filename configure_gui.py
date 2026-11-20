"""Desktop forms for the project configuration tool."""

import io
import tkinter as tk
from contextlib import redirect_stdout
from tkinter import font, messagebox, ttk


BACKGROUND = "#f1f4f9"
PAPER = "#ffffff"
INK = "#18263c"
MUTED = "#526176"
BLUE = "#204aa0"
NAV = "#142441"
LINE = "#d5deeb"
ERROR = "#a32636"


def run(config, dry_run):
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    Configurator(root, config, dry_run)
    root.mainloop()
    return True


class Configurator:
    def __init__(self, root, config, dry_run):
        self.root = root
        self.config = config
        self.dry_run = dry_run
        self.page = None
        self.read_draft = None
        self.plan_draft = None
        root.title("Board Configuration")
        root.geometry("1000x710")
        root.minsize(740, 570)
        root.configure(background=BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.style_window()

        header = ttk.Frame(root, style="Header.TFrame", padding=(24, 16))
        header.pack(fill="x")
        self.project = ttk.Label(header, style="Project.TLabel")
        self.project.pack(side="left")
        self.stage = ttk.Label(header, style="Stage.TLabel", padding=(10, 5))
        self.stage.pack(side="right")
        if dry_run:
            ttk.Label(header, text="Dry run", style="Meta.TLabel").pack(side="right", padx=14)

        body = ttk.Frame(root, style="App.TFrame")
        body.pack(fill="both", expand=True)
        sidebar = ttk.Frame(body, style="Nav.TFrame", padding=(12, 20))
        sidebar.pack(side="left", fill="y")
        self.pages = {
            "Board info": self.board_page,
            "Manufacturing": self.manufacturing_page,
            "Project stage": self.stage_page,
            "Checks & repairs": self.check_page,
        }
        self.navigation = {}
        for name in self.pages:
            button = ttk.Button(sidebar, text=name, style="Nav.TButton", width=17,
                                command=lambda page=name: self.open_page(page))
            button.pack(fill="x", pady=(0, 5))
            self.navigation[name] = button
        self.workspace = ttk.Frame(body, style="App.TFrame", padding=(24, 20))
        self.workspace.pack(side="left", fill="both", expand=True)

        footer = ttk.Frame(root, style="Header.TFrame", padding=(20, 12))
        footer.pack(fill="x")
        self.status = ttk.Label(footer, style="Status.TLabel", wraplength=480)
        self.status.pack(side="left", fill="x", expand=True)
        self.review_button = ttk.Button(footer, text="Review changes…", style="Primary.TButton",
                                        command=self.review_changes)
        self.review_button.pack(side="right")
        self.refresh_button = ttk.Button(footer, text="Reload", command=lambda: self.open_page(self.page))
        self.refresh_button.pack(side="right", padx=(10, 8))
        self.update_header()
        self.open_page("Checks & repairs" if config.project_file_problems() else "Board info")

    def style_window(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        base = font.nametofont("TkDefaultFont")
        self.section_font = font.Font(root=self.root, font=base, size=20, weight="bold")
        self.header_font = font.Font(root=self.root, font=base, size=15, weight="bold")
        style.configure(".", background=PAPER, foreground=INK, bordercolor=LINE, font=base)
        style.configure("App.TFrame", background=BACKGROUND)
        style.configure("Header.TFrame", background=PAPER)
        style.configure("Nav.TFrame", background=NAV)
        style.configure("Nav.TButton", background=NAV, foreground="#e2ebfb", anchor="w",
                        padding=(10, 9), borderwidth=0, focuscolor="#aec7ff")
        style.map("Nav.TButton", background=[("active", "#294572"), ("selected", BLUE)])
        style.configure("Page.TLabel", background=BACKGROUND, font=self.section_font)
        style.configure("Help.TLabel", background=BACKGROUND, foreground=MUTED)
        style.configure("Project.TLabel", font=self.header_font)
        style.configure("Stage.TLabel", background="#e7efff", foreground=BLUE)
        style.configure("Meta.TLabel", foreground=MUTED)
        style.configure("Status.TLabel", foreground=MUTED)
        style.configure("Error.TLabel", foreground=ERROR)
        style.configure("TButton", padding=(12, 7))
        style.configure("Primary.TButton", background=BLUE, foreground=PAPER, focuscolor="#c1d4ff")
        style.map("Primary.TButton", background=[("disabled", "#dfe5ee"), ("active", "#2b5bb9")],
                  foreground=[("disabled", MUTED)])
        style.configure("TEntry", padding=5)
        style.configure("TNotebook.Tab", padding=(12, 7))
        style.map("TNotebook.Tab", background=[("selected", PAPER)], foreground=[("selected", BLUE)])

    def update_header(self):
        config = self.config
        stage = config.read_stage()
        version = config.read_release_version() if stage == "RELEASED" else ""
        self.project.configure(text=config.find_project_stem())
        self.stage.configure(text=f"{stage.title()} {version}".strip())

    def set_status(self, text="", error=False):
        self.status.configure(text=text, style="Error.TLabel" if error else "Status.TLabel")

    def confirm_discard(self):
        return (self.read_draft is None or self.read_draft() == self.baseline
                or messagebox.askyesno("Discard edits?", "Leave this page and discard its unsaved edits?",
                                       parent=self.root, default="no"))

    def close(self):
        if self.confirm_discard():
            self.root.destroy()

    def file_state(self):
        config = self.config
        paths = [config.KIBOT_MAIN, config.CI_YAML, config.CHANGELOG, config.STACKUP_YAML,
                 config.PDF_FAB_YAML, config.IMPEDANCE_TABLE]
        paths += [path for _, path in config.MANUFACTURING_NOTES]
        for pattern in ("*.kicad_*", "fp-lib-table", "sym-lib-table"):
            paths.extend(config.PROJECT_DIR.glob(pattern))
        stamps = {}
        for path in paths:
            if path.is_file():
                stat = path.stat()
                stamps[path] = (stat.st_size, stat.st_mtime_ns)
        return stamps

    def open_page(self, name, discard=False):
        if not discard and not self.confirm_discard():
            return
        self.page = name
        for label, button in self.navigation.items():
            button.state(["selected" if name == label else "!selected"])
        for widget in self.workspace.winfo_children():
            widget.destroy()
        self.read_draft = self.plan_draft = None
        self.review_button.state(["disabled"])
        self.review_button.configure(text="Review changes…")
        self.set_status()
        try:
            self.stamps = self.file_state()
            self.pages[name]()
        except (self.config.ConfigError, OSError) as error:
            self.set_status(str(error), error=True)
            self.read_draft = self.plan_draft = None
        if self.read_draft is not None:
            self.baseline = self.read_draft()
        if self.plan_draft is not None:
            self.review_button.state(["!disabled"])

    def page_panel(self, title, description):
        ttk.Label(self.workspace, text=title, style="Page.TLabel").pack(anchor="w")
        ttk.Label(self.workspace, text=description, style="Help.TLabel", wraplength=515).pack(anchor="w", pady=(3, 14))
        panel = ttk.Frame(self.workspace, padding=16, relief="solid", borderwidth=1)
        panel.pack(fill="both", expand=True)
        return panel

    def editor(self, parent, text, height=8, readonly=False, wrap="none"):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        editor = tk.Text(frame, wrap=wrap, height=height, width=1, padx=9, pady=8,
                         relief="flat", highlightthickness=1, highlightbackground=LINE,
                         highlightcolor=BLUE, font="TkFixedFont", foreground=INK, undo=not readonly)
        editor.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=editor.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        editor.configure(yscrollcommand=scroll.set)
        if wrap == "none":
            horizontal = ttk.Scrollbar(frame, orient="horizontal", command=editor.xview)
            horizontal.grid(row=1, column=0, sticky="ew")
            editor.configure(xscrollcommand=horizontal.set)
        editor.insert("1.0", text)
        if readonly:
            editor.configure(state="disabled")
        return editor

    @staticmethod
    def editor_value(editor):
        return editor.get("1.0", "end-1c")

    def field(self, parent, label, variable, row, hint=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 16), pady=7)
        container = ttk.Frame(parent)
        container.grid(row=row, column=1, sticky="ew", pady=3)
        entry = ttk.Entry(container, textvariable=variable)
        entry.pack(fill="x")
        if hint:
            ttk.Label(container, text=hint, style="Meta.TLabel", wraplength=385).pack(anchor="w", pady=(2, 0))
        return entry

    def board_page(self):
        config = self.config
        fresh = config.is_fresh_template(config.find_project_stem())
        panel = self.page_panel("Set up this board" if fresh else "Board info",
                                "Project identity and drawing title-block fields.")
        panel.columnconfigure(1, weight=1)
        labels = ("Board name", "Board title", "Description", "Designer", "Company", "Revision")
        hints = {
            "board_name": "Lowercase letters, digits and underscores. Renaming updates the KiCad project files.",
            "title": f"Title block fits about {config.title_block_max_chars('PROJECT_NAME')} characters.",
            "designer": f"Title block fits about {config.title_block_max_chars('DESIGNER')} characters.",
            "revision": "Title-block text. Published versions come from Git tags.",
        }
        values = config.board_info()
        fields = {}
        for row, ((key, _, _), label) in enumerate(zip(config.BOARD_FIELDS, labels)):
            variable = tk.StringVar(self.root, value=values[key])
            fields[key] = (variable, self.field(panel, label, variable, row, hints.get(key, "")))
        fields["board_name"][1].focus_set()

        def draft():
            return {key: variable.get().strip() for key, (variable, _) in fields.items()}

        def build():
            values = draft()
            plan = config.Plan()
            if values == self.baseline:
                return plan
            for (key, _, validator), label in zip(config.BOARD_FIELDS, labels):
                if not fresh and values[key] == self.baseline[key]:
                    continue
                error = validator(values[key])
                if error:
                    fields[key][1].focus_set()
                    raise config.ConfigError(f"{label} · {error}")
            config.plan_board_info(plan, values)
            return plan

        self.read_draft, self.plan_draft = draft, build

    def manufacturing_page(self):
        config = self.config
        panel = self.page_panel("Manufacturing", "Drawing notes and fabrication tables.")
        kibot_text = config.read(config.KIBOT_MAIN)
        stackup = tk.BooleanVar(self.root, value=config.stackup_enabled(config.read(config.STACKUP_YAML)))
        impedance = tk.BooleanVar(self.root, value=config.impedance_enabled(kibot_text))
        switches = ttk.Frame(panel)
        switches.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(switches, text="Generate stackup", variable=stackup).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(switches, text="Generate impedance table", variable=impedance).pack(side="left")
        tabs = ttk.Notebook(panel)
        tabs.pack(fill="both", expand=True)

        def tab(label):
            page = ttk.Frame(tabs, padding=10)
            tabs.add(page, text=label)
            return page

        notes = {}
        for label, path in config.MANUFACTURING_NOTES:
            page = tab(label)
            ttk.Label(page, text="Keep numbered notes and KiBot template variables.").pack(anchor="w", pady=(0, 6))
            notes[path] = (page, self.editor(page, config.read(path) if path.exists() else ""))
        stackup_page = tab("Stackup")
        note = tk.StringVar(self.root, value=config.read_definitions(kibot_text).get("STACKUP_TABLE_NOTE", ""))
        ttk.Label(stackup_page, text="Note under the table").pack(anchor="w")
        ttk.Entry(stackup_page, textvariable=note).pack(fill="x", pady=(4, 8))
        self.editor(stackup_page, self.stackup_summary(), readonly=True)
        table_page = tab("Impedance")
        ttk.Label(table_page, text="Edit the comma-separated rows and keep the column header.").pack(anchor="w", pady=(0, 6))
        table = self.editor(table_page, config.read(config.IMPEDANCE_TABLE) if config.IMPEDANCE_TABLE.exists() else "")

        def draft():
            return (stackup.get(), impedance.get(), note.get().strip(),
                    {path: self.editor_value(editor) for path, (_, editor) in notes.items()},
                    self.editor_value(table))

        def build():
            draw, include, table_note, notes_text, table_text = draft()
            plan = config.Plan()
            if draw != self.baseline[0]:
                config.plan_stackup_generation(plan, draw)
            if include != self.baseline[1]:
                config.plan_impedance(plan, include)
            if table_note != self.baseline[2]:
                error = config.validate_stackup_note(table_note)
                if error:
                    tabs.select(stackup_page)
                    raise config.ConfigError(error)
                plan.write(config.KIBOT_MAIN, config.set_definition(plan.text_of(config.KIBOT_MAIN),
                           "STACKUP_TABLE_NOTE", table_note), "stackup table note")
            for path, value in notes_text.items():
                if value != self.baseline[3][path]:
                    if not config.parse_notes(value)["notes"]:
                        tabs.select(notes[path][0])
                        raise config.ConfigError(f"{path.name} needs at least one numbered note.")
                    plan.write(path, value, "drawing notes")
            if include or table_text != self.baseline[4]:
                if table_text != self.baseline[4] or not self.baseline[1]:
                    data = config.parse_table(table_text)
                    columns = config.table_columns(data)
                    if not all(columns) or any(len(row["fields"]) != len(columns)
                            or any(config.validate_cell(field) for field in row["fields"]) for row in data["rows"]):
                        tabs.select(table_page)
                        raise config.ConfigError("Give each impedance row a value for every column.")
                if table_text != self.baseline[4]:
                    plan.write(config.IMPEDANCE_TABLE, table_text, "impedance table rows")
            return plan

        self.read_draft, self.plan_draft = draft, build

    def stackup_summary(self):
        config = self.config
        board = config.PROJECT_DIR / f"{config.find_project_stem()}.kicad_pcb"
        layers, finish = config.read_stackup(config.read(board))
        if not layers:
            return "Set the physical stackup in KiCad Board Setup."
        summary = io.StringIO()
        with redirect_stdout(summary):
            config.print_stackup(layers, finish)
        return summary.getvalue().strip("\n")

    def show_manufacturing_review(self):
        config = self.config
        try:
            kibot_text = config.read(config.KIBOT_MAIN)
            sections = [(label, config.read(path) if path.exists() else "Template file is missing.")
                        for label, path in config.MANUFACTURING_NOTES]
            if config.stackup_enabled(config.read(config.STACKUP_YAML)):
                note = config.read_definitions(kibot_text).get("STACKUP_TABLE_NOTE", "")
                sections.append(("Stackup", self.stackup_summary() + "\n\n" + note))
            if config.impedance_enabled(kibot_text):
                table = config.read(config.IMPEDANCE_TABLE) if config.IMPEDANCE_TABLE.exists() else "Table file is missing."
                sections.append(("Impedance", table))
        except (config.ConfigError, OSError) as error:
            self.set_status(str(error), error=True)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Manufacturing review")
        dialog.transient(self.root)
        dialog.geometry("740x480")
        panel = ttk.Frame(dialog, padding=14)
        panel.pack(fill="both", expand=True)
        tabs = ttk.Notebook(panel)
        tabs.pack(fill="both", expand=True)
        for label, text in sections:
            page = ttk.Frame(tabs, padding=8)
            tabs.add(page, text=label)
            self.editor(page, text, readonly=True)
        close = ttk.Button(panel, text="Close", command=dialog.destroy)
        close.pack(anchor="e", pady=(10, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()
        close.focus_set()

    def stage_page(self):
        config = self.config
        panel = self.page_panel("Project stage", "Choose which outputs and checks run in CI.")
        current = config.read_stage()
        stage = tk.StringVar(self.root, value=current)
        choices = ttk.Combobox(panel, textvariable=stage, values=config.STAGE_NAMES, state="readonly", width=19)
        choices.pack(anchor="w")
        description = ttk.Label(panel, wraplength=490)
        description.pack(anchor="w", pady=(7, 12))
        release = ttk.Frame(panel)
        version = tk.StringVar(self.root, value=config.read_release_version() if current == "RELEASED"
                               else config.suggest_next_version(config.git_version_tags()))
        version_row = ttk.Frame(release)
        version_row.pack(fill="x", pady=(0, 10))
        ttk.Label(version_row, text="Release version").pack(side="left", padx=(0, 10))
        ttk.Entry(version_row, textvariable=version, width=15).pack(side="left")
        changelog = config.read(config.CHANGELOG) if config.CHANGELOG.exists() else ""
        unreleased = config.UNRELEASED_RE.search(changelog)
        ttk.Label(release, text="Release notes · [Unreleased]").pack(anchor="w", pady=(0, 5))
        notes = self.editor(release, unreleased[1] if unreleased else "", height=9, wrap="word")
        reviewed = tk.BooleanVar(self.root)
        review = ttk.Frame(release)
        review.pack(fill="x", pady=(8, 0))
        ttk.Button(review, text="Review manufacturing…", command=self.show_manufacturing_review).pack(side="left")
        ttk.Checkbutton(review, text="Manufacturing reviewed", variable=reviewed).pack(side="left", padx=8)

        def select(_event=None):
            _, when, what = next((item for item in config.STAGES if item[0] == stage.get()),
                                 ("", "Choose a supported project stage.", ""))
            description.configure(text=f"{when} {what}")
            if stage.get() == "RELEASED":
                release.pack(fill="both", expand=True)
            else:
                release.pack_forget()

        choices.bind("<<ComboboxSelected>>", select)
        select()

        def draft():
            return stage.get(), version.get().strip(), self.editor_value(notes)

        def build():
            requested, number, notes_text = draft()
            plan = config.Plan()
            if draft() == self.baseline:
                return plan
            if requested not in config.STAGE_NAMES:
                raise config.ConfigError("Choose a supported project stage.")
            if requested == "RELEASED":
                error = config.validate_release_version(number)
                if error:
                    raise config.ConfigError(error)
                if not reviewed.get():
                    raise config.ConfigError("Review the Manufacturing page and confirm the release review.")
                release_notes = config.read_release_notes("## [Unreleased]\n" + notes_text)
                if not any(release_notes.values()) and not messagebox.askyesno(
                    "Empty release notes", "Prepare this release with empty notes?", parent=self.root, default="no"
                ):
                    return plan
                if notes_text != self.baseline[2]:
                    plan.write(config.CHANGELOG, config.write_release_notes(changelog, release_notes), "release notes")
            else:
                number = ""
            config.plan_stage(plan, requested, number)
            return plan

        self.read_draft, self.plan_draft = draft, build

    def check_page(self):
        panel = self.page_panel("Checks & repairs", "Project files, KiBot settings, and manufacturing drawing checks.")
        problems, plan, unresolved, _ = self.config.config_check_plan()
        if not problems:
            ttk.Label(panel, text="Configuration passed all checks.").pack(anchor="w")
            return
        manual = set(unresolved)
        lines = [f"{'Review' if problem in manual else 'Found'} · {problem}" for problem in problems]
        if unresolved:
            lines += ["", "Manual follow-up"] + unresolved
        details = self.editor(panel, "\n\n".join(lines), readonly=True, wrap="word")
        details.configure(font="TkDefaultFont")
        if not plan.empty():
            self.review_button.configure(text="Review repairs…")
            self.plan_draft = lambda: plan

    def review_changes(self):
        config = self.config
        try:
            if self.file_state() != self.stamps:
                raise config.ConfigError("Project files changed on disk. Reload this page before applying edits.")
            plan = self.plan_draft()
            if plan.empty():
                self.set_status("No changes to apply.")
                return
            if config.KIBOT_MAIN in plan.writes:
                problems = config.lint(plan.text_of(config.KIBOT_MAIN))
                if problems:
                    raise config.ConfigError(problems[0])
            self.show_review(plan)
        except (config.ConfigError, OSError) as error:
            self.set_status(str(error), error=True)

    def show_review(self, plan):
        dialog = tk.Toplevel(self.root)
        dialog.title("Review changes")
        dialog.transient(self.root)
        dialog.geometry("650x340")
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="These files will change when you apply." if not self.dry_run
                  else "Dry run · Proposed file changes", font=self.header_font).pack(anchor="w", pady=(0, 10))
        self.editor(panel, plan.summary(), readonly=True, wrap="word")
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=(12, 0))

        def apply():
            config = self.config
            try:
                if self.file_state() != self.stamps:
                    raise config.ConfigError("Project files changed on disk. Reload before applying.")
                if config.kicad_is_open(config.find_project_stem()):
                    raise config.ConfigError("Close this project in KiCad before applying changes.")
                with redirect_stdout(io.StringIO()):
                    applied = config.commit(plan, dry_run=False, confirm=False)
                if not applied:
                    raise config.ConfigError("The configuration changes could not be applied.")
            except (config.ConfigError, OSError) as error:
                messagebox.showerror("Changes not applied", str(error), parent=dialog)
                return
            dialog.destroy()
            self.update_header()
            self.open_page(self.page, discard=True)
            self.set_status("Saved to this checkout.")

        cancel = ttk.Button(actions, text="Close" if self.dry_run else "Back", command=dialog.destroy)
        if not self.dry_run:
            ttk.Button(actions, text="Apply changes", style="Primary.TButton", command=apply).pack(side="right")
        cancel.pack(side="right", padx=(0, 8))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()
        cancel.focus_set()
