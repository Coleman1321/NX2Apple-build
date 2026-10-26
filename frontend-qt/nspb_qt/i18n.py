"""Language choice: Chinese on Chinese devices, English everywhere else."""
from __future__ import annotations

import locale
import os
import sys
from enum import Enum


class Lang(Enum):
    ZH = 'zh'
    EN = 'en'

    @property
    def other(self) -> 'Lang':
        return Lang.EN if self is Lang.ZH else Lang.ZH

    @property
    def toggle_label(self) -> str:
        return 'EN' if self is Lang.ZH else '中文'

    @staticmethod
    def initial() -> 'Lang':
        """Saved choice, else the device language: any Chinese variant is Chinese, everything
        else is English (the same rule the SwiftUI app uses)."""
        saved = os.environ.get('NSPB_LANG', '')
        if saved in ('zh', 'en'):
            return Lang(saved)
        try:
            tag = locale.getlocale()[0] or ''
        except (ValueError, TypeError):
            tag = ''
        tag = tag or os.environ.get('LANG', '') or os.environ.get('LC_ALL', '')
        if not tag and sys.platform.startswith('win'):
            import ctypes
            try:
                buf = ctypes.create_unicode_buffer(85)
                ctypes.windll.kernel32.GetUserDefaultUILanguage()  # noqa: F841  (kept for clarity)
                ctypes.windll.kernel32.GetLocaleInfoW(0x0800, 0x00000002, buf, 85)  # LOCALE_SISO639LANGNAME
                tag = buf.value
            except Exception:
                tag = ''
        return Lang.ZH if tag.lower().startswith('zh') else Lang.EN
