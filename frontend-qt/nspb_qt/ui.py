"""The window: header, repository, inputs, dependencies, build, log. Mirrors the SwiftUI app."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import platform_util as pu
from .model import Dep, DepState, Model


class MainWindow(QMainWindow):
    def __init__(self, model: Model) -> None:
        super().__init__()
        self.m = model
        self.setWindowTitle('NS Port Builder')
        self.resize(980, 900)
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
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._build_header()
        self._build_repository()
        self._build_inputs()
        self._build_deps()
        self._build_actions()
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

    # ---------------------------------------------------------------- sections

    def _build_header(self) -> None:
        row = QHBoxLayout()
        title = QLabel('NS Port Builder')
        f = title.font()
        f.setPointSize(20)
        f.setBold(True)
        title.setFont(f)
        self.subtitle = QLabel(self.m.t('app.subtitle'))
        self.subtitle.setStyleSheet('color: palette(mid);')
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(title)
        left.addWidget(self.subtitle)
        row.addLayout(left)
        row.addStretch(1)
        self.lang_btn = QPushButton(self.m.lang.toggle_label)
        self.lang_btn.clicked.connect(self._toggle_lang)
        row.addWidget(self.lang_btn, 0, Qt.AlignTop)
        self.body.addLayout(row)

    def _build_repository(self) -> None:
        box = QGroupBox(self.m.t('repo.title'))
        self.repo_box = box
        lay = QVBoxLayout(box)
        note = QLabel(self.m.t('repo.note'))
        note.setStyleSheet('color: palette(mid);')
        lay.addWidget(note)
        row = QHBoxLayout()
        self.repo_path_label = QLabel('')
        self.repo_path_label.setFont(self._mono)
        self.repo_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.repo_path_label, 1)
        self.choose_btn = QPushButton(self.m.t('repo.choose'))
        self.choose_btn.clicked.connect(self._choose_repo)
        row.addWidget(self.choose_btn)
        lay.addLayout(row)
        self.repo_status = QLabel('')
        self.repo_status.setStyleSheet('color: palette(mid);')
        lay.addWidget(self.repo_status)
        box.setStyleSheet('QGroupBox { margin-top: 10px; padding-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }')
        self.body.addWidget(box)

    def _build_inputs(self) -> None:
        box = QGroupBox(self.m.t('data.title'))
        self.data_box = box
        lay = QVBoxLayout(box)
        note = QLabel(self.m.t('data.note'))
        note.setStyleSheet('color: palette(mid);')
        lay.addWidget(note)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.input_labels: dict[str, QLabel] = {}
        rows = [('base', 'data.base'), ('update', 'data.update'), ('dlc', 'data.dlc'), ('keys', 'data.keys')]
        for i, (key, l10n) in enumerate(rows):
            name = QLabel(self.m.t(l10n))
            val = QLabel('—')
            val.setFont(self._mono)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setStyleSheet('color: palette(mid);')
            grid.addWidget(name, i, 0)
            grid.addWidget(val, i, 1)
            self.input_labels[key] = val
        lay.addLayout(grid)
        row = QHBoxLayout()
        self.folder_label = QLabel(self.m.t('data.folderHint'))
        self.folder_label.setStyleSheet('color: palette(mid);')
        row.addWidget(self.folder_label, 1)
        pick = QPushButton(self.m.t('data.pickFolder'))
        pick.clicked.connect(self._pick_folder)
        row.addWidget(pick)
        lay.addLayout(row)
        box.setStyleSheet('QGroupBox { margin-top: 10px; padding-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }')
        self.body.addWidget(box)

    def _build_deps(self) -> None:
        box = QGroupBox(self.m.t('dep.title'))
        self.deps_box = box
        lay = QVBoxLayout(box)
        head = QHBoxLayout()
        self.deps_summary = QLabel('')
        head.addWidget(self.deps_summary, 1)
        recheck = QPushButton(self.m.t('dep.recheck'))
        recheck.clicked.connect(self.m.check_deps)
        head.addWidget(recheck)
        lay.addLayout(head)
        self.deps_container = QVBoxLayout()
        lay.addLayout(self.deps_container)
        box.setStyleSheet('QGroupBox { margin-top: 10px; padding-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }')
        self.body.addWidget(box)

    def _build_actions(self) -> None:
        row = QHBoxLayout()
        self.build_btn = QPushButton(self.m.t('build.start'))
        self.build_btn.setMinimumHeight(38)
        f = self.build_btn.font()
        f.setPointSize(13)
        f.setBold(True)
        self.build_btn.setFont(f)
        self.build_btn.clicked.connect(self.m.start_build)
        row.addWidget(self.build_btn, 1)
        self.out_btn = QPushButton(self.m.t('build.outDir'))
        self.out_btn.clicked.connect(self._choose_out)
        row.addWidget(self.out_btn)
        self.body.addLayout(row)
        self.stages_container = QVBoxLayout()
        self.body.addLayout(self.stages_container)
        self.body.addStretch(1)

    def _build_log(self) -> None:
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(self._mono)
        self.log.setPlaceholderText(self.m.t('log.placeholder'))
        self.log.setMinimumHeight(150)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body.addWidget(self.log, 1)

    def _build_footer(self) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(16, 8, 16, 10)
        self.footer = QLabel('')
        row.addWidget(self.footer, 1)
        wrap = QWidget()
        wrap.setLayout(row)
        self.centralWidget().layout().addWidget(wrap)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # ---------------------------------------------------------------- refresh

    def _refresh_all(self) -> None:
        self.subtitle.setText(self.m.t('app.subtitle'))
        self.lang_btn.setText(self.m.lang.toggle_label)
        self.repo_box.setTitle(self.m.t('repo.title'))
        self.choose_btn.setText(self.m.t('repo.choose'))
        self.data_box.setTitle(self.m.t('data.title'))
        self.deps_box.setTitle(self.m.t('dep.title'))
        if self.m.repo_ok:
            self.repo_path_label.setText(pu.short_path(self.m.repo_path))
            self.repo_path_label.setStyleSheet('')
            self.repo_status.setText(self.m.t('repo.ok') if self.m.repo_is_git else self.m.t('repo.noGit'))
        else:
            self.repo_path_label.setText(self.m.repo_path or self.m.t('repo.notFound'))
            self.repo_path_label.setStyleSheet('color: palette(highlight);')
            self.repo_status.setText(self.m.t('repo.firstHint'))
        for key, lbl in self.input_labels.items():
            v = {'base': self.m.base_path, 'update': self.m.update_path,
                 'keys': self.m.keys_path}.get(key)
            if key == 'dlc':
                v = f'{len(self.m.dlc_paths)} 个' if self.m.dlc_paths else ''
            lbl.setText(Path(v).name if v else '—')
            lbl.setStyleSheet('' if v else 'color: palette(mid);')
        self.folder_label.setText(pu.short_path(self.m.game_dir) if self.m.game_dir else self.m.t('data.folderHint'))
        self._refresh_deps()

    def _refresh_deps(self) -> None:
        while self.deps_container.count():
            item = self.deps_container.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        for d in self.m.deps:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 1, 0, 1)
            mark = QLabel('✓' if d.ok else ('!' if d.state is DepState.OLD else '✗'))
            mark.setFixedWidth(18)
            mark.setStyleSheet(f'color: {"#2e9e4f" if d.ok else "#c0392b"}; font-weight: bold;')
            h.addWidget(mark)
            h.addWidget(QLabel(self.m.t(d.title_key)), 0)
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
            lab.setFont(self._mono)
            lab.setStyleSheet('color: palette(mid);')
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
                    hint.setStyleSheet('color: palette(mid);')
                    h.addWidget(hint)
            self.deps_container.addWidget(row)
        if self.m.deps_checked:
            n_ok = sum(1 for d in self.m.deps if d.ok)
            if self.m.all_deps_ok:
                self.deps_summary.setText(self.m.t('dep.allReady'))
                self.deps_summary.setStyleSheet('color: #2e9e4f;')
            else:
                self.deps_summary.setText(self.m.t('dep.missing', len(self.m.deps) - n_ok))
                self.deps_summary.setStyleSheet('color: #c0392b;')
        else:
            self.deps_summary.setText(self.m.t('dep.checking'))
            self.deps_summary.setStyleSheet('color: palette(mid);')
        self._refresh_running()

    def _refresh_stages(self) -> None:
        while self.stages_container.count():
            item = self.stages_container.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        for st in self.m.stages:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 1, 0, 1)
            mark = {'done': '✓', 'running': '…', 'failed': '✗'}.get(st.state, '·')
            colour = {'done': '#2e9e4f', 'failed': '#c0392b'}.get(st.state, 'palette(mid)')
            lab = QLabel(mark)
            lab.setFixedWidth(16)
            lab.setStyleSheet(f'color: {colour};')
            h.addWidget(lab)
            h.addWidget(QLabel(st.name), 0)
            det = QLabel(st.detail)
            det.setFont(self._mono)
            det.setStyleSheet('color: palette(mid);')
            h.addWidget(det, 1)
            self.stages_container.addWidget(row)

    def _refresh_running(self) -> None:
        running = self.m.running
        self.build_btn.setText(self.m.t('build.cancel') if running else self.m.t('build.start'))
        self.build_btn.setEnabled(running or self.m.can_build)
        if not running:
            try:
                self.build_btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.build_btn.clicked.connect(self.m.cancel_build if running else self.m.start_build)

    def _append_log(self, s: str) -> None:
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(s)
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)

    def _on_finished(self, ok: bool, note: str) -> None:
        if ok:
            msg = self.m.t('msg.done') if not note else note
            if self.m.ipa_path:
                msg += '\n' + self.m.t('msg.ipaAt', self.m.ipa_path)
            if self.m.archive_path:
                msg += '\n' + self.m.t('msg.archiveAt', self.m.archive_path)
            self.footer.setText(msg)
            self.footer.setStyleSheet('color: #2e9e4f;')
        else:
            self.footer.setText(note or self.m.t('msg.buildFailed'))
            self.footer.setStyleSheet('color: #c0392b;')

    # ---------------------------------------------------------------- actions

    def _toggle_lang(self) -> None:
        self.m.toggle_lang()
        self._refresh_all()

    def _choose_repo(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.m.t('repo.pickMessage'))
        if d:
            self.m.repo_path = d
            self.m.repoChanged.emit()

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.m.t('data.pickFolder'))
        if d:
            self.m.scan_game_dir(d)

    def _choose_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.m.t('build.outDir'))
        if d:
            self.m.out_dir = d
            self._refresh_all()
