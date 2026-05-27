from __future__ import annotations

import os

from pump_web.ui import _UI_CSS, _UI_THEME, DEFAULT_WEBUI_PORT, build_ui

demo = build_ui()

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PUMP_WEBUI_PORT", str(DEFAULT_WEBUI_PORT))),
        share=False,
        theme=_UI_THEME,
        css=_UI_CSS,
    )
