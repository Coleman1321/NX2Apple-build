"""The window: header, repository, inputs, dependencies, build progress, log.

The layout follows the SwiftUI app section for section, so a user who has seen one recognises
the other: rounded cards on a dark background, a coloured dot per row, monospaced paths.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from . import platform_util as pu
from .model import DepState, Model
from .style import GREEN, MUTED, ORANGE, RED


class MainWindow(QMainWindow):
    def __init__(self, model: Model) -> None:
        super().__init__()
        self.m = model
        self.setWindowTitle('NS Port Builder')
        # Size to the screen, not to a fixed 1000x980: on a handheld's 1280x800 panel a fixed
        # height puts the footer below the screen edge and the window cannot be shrunk enough to
        # reach it. Fit within 90% of the available area and let the scroll area do the rest.
        avail = self.screen().availableGeometry() if self.screen() else None
        if avail is not None:
            # Use most of the panel: a 1280x800 handheld at 150% has only ~853x533 logical pixels,
            # so the margins must be small and the height is what matters.
            self.resize(min(900, int(avail.width() * 0.98)), min(900, int(avail.height() * 0.96)))
        else:
            self.resize(900, 800)
        self.setMinimumSize(420, 300)   # the scroll area carries everything below this
        self._mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName('body')
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(12, 10, 12, 10)
        self.body.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._build_header()
        self._build_repository()
        self._build_inputs()
        self._build_deps()
        self._build_progress()
        self._build_log()
        outer.addWidget(self._separator())
        self._build_footer()

        self.m.depsChanged.connect(self._refresh_deps)
        self.m.repoChanged.connect(self._refresh_all)
        self.m.stagesChanged.connect(self._refresh_stages)
        self.m.logAppended.connect(self._append_log)
        self.m.runningChanged.connect(self._refresh_running)
        self.m.finished.connect(self._on_finished)

        self._refresh_all()
        self.m.check_deps()

    # ---------------------------------------------------------------- header

    def _build_header(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        badge = QLabel('🎮')
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f'background: {GREEN}; border-radius: 10px; font-size: 18px;')
        row.addWidget(badge)
        left = QVBoxLayout()
        left.setSpacing(3)
        self.title = QLabel('NS Port Builder')
        self.title.setObjectName('title')
        self.subtitle = QLabel(self.m.t('app.subtitle'))
        self.subtitle.setObjectName('subtitle')
        left.addWidget(self.title)
        left.addWidget(self.subtitle)
        row.addLayout(left)
        row.addStretch(1)
        self.lang_btn = QPushButton(self.m.lang.toggle_label)
        self.lang_btn.clicked.connect(self._toggle_lang)
        row.addWidget(self.lang_btn, 0, Qt.AlignTop)
        self.body.addLayout(row)

    # ---------------------------------------------------------------- cards

    def _card(self, title: str, note: str = '') -> tuple[QFrame, QVBoxLayout]:
        box = QFrame()
        box.setObjectName('card')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        t = QLabel(title)
        f = t.font()
        f.setBold(True)
        f.setPointSize(13)
        t.setFont(f)
        head.addWidget(t)
        if note:
            n = QLabel(note)
            n.setObjectName('note')
            head.addWidget(n)
        head.addStretch(1)
        lay.addLayout(head)
        self.body.addWidget(box)
        return box, lay

    def _build_repository(self) -> None:
        box, lay = self._card(self.m.t('repo.title'), self.m.t('repo.note'))
        self.repo_box = box
        row = QHBoxLayout()
        self.repo_dot = QLabel('●')
        self.repo_dot.setFixedWidth(14)
        row.addWidget(self.repo_dot)
        self.repo_path_label = QLabel('')
        self.repo_path_label.setObjectName('mono')
        self.repo_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.repo_path_label, 1)
        self.choose_btn = QPushButton(self.m.t('repo.choose'))
        self.choose_btn.clicked.connect(self._choose_repo)
        row.addWidget(self.choose_btn)
        lay.addLayout(row)
        # A machine without a clone gets Download; a clone gets Check/Pull. Same as the macOS app.
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.download_btn = QPushButton(self.m.t('repo.download'))
        self.download_btn.clicked.connect(lambda: self.m.clone_repo())
        self.check_btn = QPushButton(self.m.t('repo.check'))
        self.check_btn.clicked.connect(self.m.check_repo_updates)
        self.pull_btn = QPushButton(self.m.t('repo.pull'))
        self.pull_btn.clicked.connect(self.m.pull_repo)
        for b in (self.download_btn, self.check_btn, self.pull_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)
        self.repo_status = QLabel('')
        self.repo_status.setObjectName('note')
        lay.addWidget(self.repo_status)

    def _build_inputs(self) -> None:
        box, lay = self._card(self.m.t('data.title'), self.m.t('data.note'))
        self.data_box = box
        self.folder_label = QLabel(self.m.t('data.folderHint'))
        self.folder_label.setObjectName('mono')
        lay.addWidget(self.folder_label)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(2, 1)
        self.input_rows: dict[str, tuple[QLabel, QLabel]] = {}
        specs = [('base', 'data.base', False), ('update', 'data.update', True),
                 ('dlc', 'data.dlc', True), ('keys', 'data.keys', False)]
        for i, (key, l10n, optional) in enumerate(specs):
            dot = QLabel('○')
            dot.setFixedWidth(14)
            name = QLabel(self.m.t(l10n))
            name.setFixedWidth(110)
            val = QLabel('—')
            val.setObjectName('mono')
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            btn = QPushButton(self.m.t('data.choose'))
            btn.setFixedWidth(72)
            btn.clicked.connect(lambda _=False, k=key: self._choose_input(k))
            grid.addWidget(dot, i, 0)
            grid.addWidget(name, i, 1)
            grid.addWidget(val, i, 2)
            grid.addWidget(btn, i, 3)
            self.input_rows[key] = (dot, val)
        lay.addLayout(grid)
        row = QHBoxLayout()
        row.addStretch(1)
        pick = QPushButton(self.m.t('data.pickFolder'))
        pick.clicked.connect(self._pick_folder)
        row.addWidget(pick)
        lay.addLayout(row)

    def _build_deps(self) -> None:
        box, lay = self._card(self.m.t('dep.title'))
        self.deps_box = box
        head = QHBoxLayout()
        self.deps_summary = QLabel('')
        head.addWidget(self.deps_summary)
        head.addStretch(1)
        self.install_all_btn = QPushButton(self.m.t('dep.installAll'))
        self.install_all_btn.clicked.connect(self.m.install_all_missing)
        head.addWidget(self.install_all_btn)
        recheck = QPushButton(self.m.t('dep.recheck'))
        recheck.clicked.connect(self.m.check_deps)
        head.addWidget(recheck)
        lay.addLayout(head)
        self.deps_container = QVBoxLayout()
        self.deps_container.setSpacing(3)
        lay.addLayout(self.deps_container)

    def _build_progress(self) -> None:
        box, lay = self._card(self.m.t('prog.title'))
        self.progress_box = box
        self.progress_box.setVisible(False)
        self.overall = QProgressBar()
        self.overall.setTextVisible(False)
        lay.addWidget(self.overall)
        self.stages_container = QVBoxLayout()
        self.stages_container.setSpacing(3)
        lay.addLayout(self.stages_container)

    def _build_log(self) -> None:
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(self._mono)
        self.log.setPlaceholderText(self.m.t('log.placeholder'))
        self.log.setMinimumHeight(90)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body.addWidget(self.log, 1)

    def _build_footer(self) -> None:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(12, 6, 12, 8)
        row.setSpacing(10)
        self.build_btn = QPushButton(self.m.t('build.start'))
        self.build_btn.setObjectName('primary')
        self.build_btn.setMinimumWidth(110)
        self.build_btn.clicked.connect(self._build_clicked)
        row.addWidget(self.build_btn)
        self.footer = QLabel('')
        self.footer.setObjectName('footer')
        row.addWidget(self.footer, 1)
        self.out_btn = QPushButton(self.m.t('build.outDir'))
        self.out_btn.clicked.connect(self._choose_out)
        row.addWidget(self.out_btn)
        self.centralWidget().layout().addWidget(wrap)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet('color: #31373f;')
        return line

    # ---------------------------------------------------------------- refresh

    def _refresh_all(self) -> None:
        self.subtitle.setText(self.m.t('app.subtitle'))
        self.lang_btn.setText(self.m.lang.toggle_label)
        self.repo_path_label.setText(
            pu.short_path(self.m.repo_path) if self.m.repo_ok
            else (self.m.repo_path or self.m.t('repo.notFound')))
        if self.m.repo_ok:
            self.repo_dot.setStyleSheet(f'color: {GREEN};')
            self.repo_status.setText(self.m.repo_status or
                                     (self.m.t('repo.ok') if self.m.repo_is_git else self.m.t('repo.noGit')))
        else:
            self.repo_dot.setStyleSheet(f'color: {RED};')
            self.repo_status.setText(self.m.repo_status or self.m.t('repo.firstHint'))
        # Download when there is no usable checkout; Check/Pull when there is a git one.
        self.download_btn.setVisible(not self.m.repo_ok)
        self.check_btn.setVisible(self.m.repo_ok and self.m.repo_is_git)
        self.pull_btn.setVisible(self.m.repo_ok and self.m.repo_is_git)
        busy = self.m.repo_busy or self.m.running
        for b in (self.download_btn, self.check_btn, self.pull_btn, self.choose_btn):
            b.setEnabled(not busy)
        self._refresh_inputs()
        self._refresh_deps()

    def _refresh_inputs(self) -> None:
        self.folder_label.setText(pu.short_path(self.m.game_dir) if self.m.game_dir
                                  else self.m.t('data.folderHint'))
        vals = {'base': self.m.base_path, 'update': self.m.update_path, 'keys': self.m.keys_path}
        for key, (dot, val) in self.input_rows.items():
            if key == 'dlc':
                n = len(self.m.dlc_paths)
                text = (Path(self.m.dlc_paths[0]).name + (f'  +{n - 1}' if n > 1 else '')) if n else ''
                set_, optional = bool(n), True
            else:
                v = vals.get(key, '')
                text, set_, optional = (Path(v).name if v else ''), bool(v), key == 'update'
            if set_:
                dot.setText('●')
                dot.setStyleSheet(f'color: {GREEN};')
                val.setText(text)
                val.setStyleSheet(f'color: {MUTED};')
            else:
                dot.setText('○' if optional else '✕')
                dot.setStyleSheet(f'color: {MUTED if optional else RED};')
                val.setText(self.m.t('data.notSelectedOptional') if optional else self.m.t('data.notSelected'))
                val.setStyleSheet(f'color: {MUTED if optional else ORANGE};')
        self._refresh_running()

    def _refresh_deps(self) -> None:
        while self.deps_container.count():
            item = self.deps_container.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        for d in self.m.deps:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            mark = QLabel('●' if d.ok else ('◐' if d.state is DepState.OLD else '✕'))
            mark.setFixedWidth(14)
            mark.setStyleSheet(f'color: {GREEN if d.ok else (ORANGE if d.state is DepState.OLD else RED)};')
            h.addWidget(mark)
            name = QLabel(self.m.t(d.title_key))
            name.setFixedWidth(140)
            h.addWidget(name)
            detail = d.detail
            if detail.startswith('dep.'):
                if ':' in detail:
                    key, arg = detail.split(':', 1)
                    detail = self.m.t(key, arg)
                else:
                    detail = self.m.t(detail)
            elif detail:
                detail = pu.short_path(detail)
            lab = QLabel(detail)
            lab.setObjectName('mono')
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            h.addWidget(lab, 1)
            if not d.ok:
                if d.install:
                    btn = QPushButton(self.m.t('dep.install'))
                    btn.setEnabled(not d.installing)
                    btn.clicked.connect(lambda _=False, dep=d: self.m.install_dep(dep))
                    h.addWidget(btn)
                else:
                    hint = QLabel(self.m.t(d.hint_key))
                    hint.setObjectName('note')
                    h.addWidget(hint)
            self.deps_container.addWidget(row)
        if self.m.deps_checked:
            if self.m.all_deps_ok:
                self.deps_summary.setText('●  ' + self.m.t('dep.allReady'))
                self.deps_summary.setStyleSheet(f'color: {GREEN}; font-weight: 600;')
            else:
                n = sum(1 for d in self.m.deps if not d.ok)
                self.deps_summary.setText(self.m.t('dep.missing', n))
                self.deps_summary.setStyleSheet(f'color: {RED}; font-weight: 600;')
        else:
            self.deps_summary.setText(self.m.t('dep.checking'))
            self.deps_summary.setStyleSheet(f'color: {MUTED};')
        missing_installable = [d for d in self.m.deps if not d.ok and d.install]
        self.install_all_btn.setVisible(bool(missing_installable))
        self.install_all_btn.setEnabled(bool(missing_installable) and
                                        not any(d.installing for d in self.m.deps))
        self._refresh_running()

    def _refresh_stages(self) -> None:
        while self.stages_container.count():
            item = self.stages_container.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        if not self.m.stages:
            self.progress_box.setVisible(False)
            return
        self.progress_box.setVisible(True)
        for st in self.m.stages:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            mark = {'done': '●', 'running': '◐', 'failed': '✕'}.get(st.state, '○')
            colour = {'done': GREEN, 'failed': RED}.get(st.state, MUTED)
            lab = QLabel(mark)
            lab.setFixedWidth(14)
            lab.setStyleSheet(f'color: {colour};')
            h.addWidget(lab)
            name = QLabel(st.name)
            h.addWidget(name, 0)
            if st.state == 'running':
                bar = QProgressBar()
                bar.setTextVisible(False)
                bar.setFixedWidth(150)
                bar.setRange(0, 0)
                h.addWidget(bar)
            det = QLabel(st.detail)
            det.setObjectName('mono')
            h.addWidget(det, 1)
            self.stages_container.addWidget(row)
        done = sum(1 for s in self.m.stages if s.state == 'done')
        self.overall.setRange(0, len(self.m.stages))
        self.overall.setValue(done)

    def _refresh_running(self) -> None:
        running = self.m.running
        self.build_btn.setText(self.m.t('build.cancel') if running else self.m.t('build.start'))
        self.build_btn.setObjectName('danger' if running else 'primary')
        self.build_btn.style().unpolish(self.build_btn)
        self.build_btn.style().polish(self.build_btn)
        self.build_btn.setEnabled(running or self.m.can_build)
        if not running and not self.footer.text():
            if not self.m.base_path:
                self.footer.setText(self.m.t('status.needInputs'))
            elif not self.m.repo_ok:
                self.footer.setText(self.m.t('status.chooseRepo'))

    def _append_log(self, s: str) -> None:
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(s)
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)

    def _on_finished(self, ok: bool, note: str) -> None:
        if ok:
            msg = note or self.m.t('msg.done')
            if self.m.ipa_path:
                msg += '   ' + self.m.t('msg.ipaAt', self.m.ipa_path)
            if self.m.archive_path:
                msg += '   ' + self.m.t('msg.archiveAt', self.m.archive_path)
            self.footer.setStyleSheet(f'color: {GREEN};')
        else:
            msg = note or self.m.t('msg.buildFailed')
            self.footer.setStyleSheet(f'color: {RED};')
        self.footer.setText(msg)
        self._refresh_running()

    # ---------------------------------------------------------------- actions

    def _toggle_lang(self) -> None:
        self.m.toggle_lang()
        self._refresh_all()

    def _build_clicked(self) -> None:
        if self.m.running:
            self.m.cancel_build()
        else:
            self.footer.setText('')
            self.footer.setStyleSheet('')
            self.m.start_build()

    def _choose_repo(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.m.t('repo.pickMessage'))
        if d:
            self.m.repo_path = d
            self.m.repoChanged.emit()

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.m.t('data.pickFolder'))
        if d:
            self.m.scan_game_dir(d)

    def _choose_input(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.m.t('data.choose'))
        if not path:
            return
        if key == 'base':
            self.m.base_path = path
        elif key == 'update':
            self.m.update_path = path
        elif key == 'keys':
            self.m.keys_path = path
        else:
            if path not in self.m.dlc_paths:
                self.m.dlc_paths.append(path)
        self.m.repoChanged.emit()

    def _choose_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.m.t('build.outDir'))
        if d:
            self.m.out_dir = d
            self._refresh_all()
