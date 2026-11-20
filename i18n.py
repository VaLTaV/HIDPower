"""Internacionalização (PT-BR e EN) para interface, bandeja, tooltips e assistente."""

from __future__ import annotations

SUPPORTED_LANGUAGES: tuple[str, ...] = ("pt-BR", "en")
LANGUAGE_LABELS: dict[str, str] = {
    "pt-BR": "Português (Brasil)",
    "en": "English",
}


def normalize_language(lang: str | None) -> str:
    """Normaliza código de idioma para 'pt-BR' ou 'en'."""
    raw = str(lang or "").strip().lower()
    if raw.startswith("en"):
        return "en"
    return "pt-BR"


TRANSLATIONS: dict[str, dict[str, str]] = {
    "pt-BR": {
        "app_title": "HIDPower",
        "tab_devices": "Dispositivos",
        "tab_settings": "Configurações",
        "tab_pin": "Como Fixar na Barra",
        "tab_about": "Sobre",
        # Dispositivos
        "btn_refresh": "Atualizar agora",
        "btn_hide": "Ocultar",
        "btn_show": "Exibir",
        "empty_title": "Nenhum periférico sem fio compatível detectado agora.",
        "empty_subtitle": "Conecte seu receptor 2.4 GHz ou dispositivo Bluetooth e clique em 'Atualizar agora'.",
        "card_last_updated": "Última carga lida: {last}  •  Atualizado às {updated}",
        "card_sleep_with_pct": "Sleep ({pct}%)",
        "card_sleep": "Sleep",
        "na": "N/A",
        "last_reading_at": "{pct}% às {when}",
        # Configurações
        "settings_title": "Preferências do HIDPower",
        "settings_language_label": "Idioma / Language:",
        "settings_interval_label": "Intervalo de atualização:",
        "settings_monitor_label": "Exibir widget no Monitor:",
        "widget_disabled": "Desativado (apenas bandeja principal)",
        "widget_monitor_offline": "Monitor desconectado ({device})",
        "btn_reanchor": "Reencaixar",
        "chk_startup": "Iniciar com o Windows",
        "chk_hide_unsupported": "Ocultar dispositivos sem telemetria USB na bandeja (ex.: fone Morcego no 2.4 GHz)",
        "settings_folder_title": "Pasta de dados e logs do HIDPower",
        "btn_open_folder": "Abrir pasta",
        "btn_run_wizard": "Alterar pasta...",
        # Guia de fixação
        "pin_heading": "Como deixar os ícones sempre visíveis ao lado do ícone de Internet",
        "pin_intro": "Por padrão do Windows 11/10, todo aplicativo novo começa recolhido dentro da seta (^) perto do relógio. Você só precisa fixar uma única vez:",
        "pin_step1_title": "Jeito 1 — Mais rápido (arrastar e soltar)",
        "pin_step1_body": (
            "1. Clique na seta (^) na barra de tarefas, ao lado do relógio.\n"
            "2. Segure e arraste o ícone do Mouse / Controle diretamente para o espaço ao lado do símbolo de Internet e Som.\n"
            "3. Solte o botão do mouse: pronto, o ícone ficará fixo ali!"
        ),
        "pin_step2_title": "Jeito 2 — Pelas Configurações do Windows 11",
        "pin_step2_body": (
            "1. Clique no botão azul abaixo para abrir as Configurações da Barra de Tarefas.\n"
            "2. Expanda a seção 'Outros ícones da bandeja do sistema'.\n"
            "3. Ative a chave para 'HIDPower' (ou os ícones dos periféricos)."
        ),
        "pin_step3_title": "Observação importante sobre fixação permanente",
        "pin_step3_body": (
            "Depois de posicionar o HIDPower.exe sempre na mesma pasta, o Windows memoriza a posição fixa mesmo após reiniciar o PC."
        ),
        "btn_taskbar_settings": "Abrir Configurações da Barra de Tarefas",
        "taskbar_err_title": "Barra de Tarefas",
        "taskbar_err_msg": (
            "Não foi possível abrir as Configurações automaticamente.\n\n"
            "Abra manualmente: Configurações > Personalização > Barra de tarefas > Outros ícones da bandeja do sistema.\n\n"
            "Detalhe: {err}"
        ),
        # Sobre
        "about_heading": "Como o HIDPower funciona por baixo dos panos",
        "about_s1_title": "Descoberta automática e unificação Compx (2.4 GHz + Cabo USB)",
        "about_s1_body": (
            "• Mouse Compx (25A7:FA07 / 25A7:FA08): unificado em um único ícone e cartão. "
            "Ao plugar o cabo USB para carregar, o modo cabo (FA08) assume automaticamente "
            "com status 'Carregando via USB' e raio, suprimindo a duplicata 2.4G em sleep.\n"
            "• Controles XInput (Slots 0..3): consulta xinput1_4.dll (XInputGetBatteryInformation).\n"
            "• Periféricos Bluetooth: consulta nativamente o Windows (cfgmgr32 / DEVPKEY_Bluetooth_Battery)."
        ),
        "about_s2_title": "Legenda das cores, modo Sleep e monitor secundário",
        "about_s2_body": (
            "• Barra Verde (> 20%) | Amarela (11% a 20%) | Vermelha (<= 10%) | Raio (Carregando).\n"
            "• Mouse em Sleep: o ícone continua visível com marca 'Z' e barra suave preservando a última leitura.\n"
            "• Múltiplos monitores: ative 'Exibir widget no Monitor' em Configurações para mostrar a mini-barra "
            "diretamente na barra de tarefas de outro monitor."
        ),
        "about_s3_title": "Por que alguns headsets 2.4 GHz são ocultados automaticamente",
        "about_s3_body": (
            "• Alguns dongles USB de áudio (como o Fallen Morcego Pro Wireless 3206:0881) expõem apenas "
            "áudio USB e teclas de mídia, sem telemetria de bateria pela USB.\n"
            "• Eles começam ocultos na bandeja no 2.4 GHz, mas você pode alternar com o botão Ocultar/Exibir."
        ),
        "btn_hid_diag": "Ver Diagnóstico USB (HID)",
        "hid_diag_title": "Diagnóstico USB (HID) e Bluetooth",
        # Rodapé
        "chk_dont_show": "Não mostrar esta janela ao iniciar",
        "btn_minimize": "Minimizar para Bandeja",
        # Bandeja e Widget
        "tray_no_devices": "Nenhum dispositivo detectado",
        "tray_no_visible": "HIDPower: Nenhum dispositivo visível",
        "menu_open_dashboard": "Abrir Painel...",
        "menu_pin_guide": "Como fixar na barra de tarefas...",
        "menu_widget_monitor": "Exibir widget no Monitor",
        "menu_refresh": "Atualizar agora",
        "menu_hide_unsupported": "Ocultar dispositivos sem telemetria",
        "menu_startup": "Iniciar com o Windows",
        "menu_quit": "Sair",
        "menu_reanchor_widget": "Reencaixar widget na barra de tarefas",
        "widget_pos_above": "Posicionar acima da barra de tarefas",
        "widget_pos_over": "Posicionar sobre a barra de tarefas",
        "widget_reanchor": "Reencaixar na posição padrão",
        "widget_move_monitor": "Mover para Monitor",
        "widget_close": "Fechar widget",
        # Monitores
        "monitor_primary": "Principal",
        "monitor_secondary": "Secundário",
        "monitor_label": "Monitor {index} ({role} — {width}×{height})",
        # Mensagens de erro / instância única
        "already_running": "O HIDPower já está em execução na bandeja do sistema.",
        "startup_err_title": "Erro de Inicialização",
        "startup_err_msg": "Não foi possível alterar o atalho de inicialização:\n{err}",
        "startup_tray_err": "Não foi possível atualizar a inicialização com o Windows:\n{err}",
        # Detalhes de dispositivos & tooltips
        "detail_compx_charging": "Carregando via USB",
        "detail_compx_charging_full": "Carregando via USB (carga completa)",
        "detail_compx_24g": "Conectado 2.4 GHz (passos de 10%)",
        "detail_compx_sleep": "Desligado / Sleep por inatividade",
        "detail_compx_sleep_no_reply": "Desligado / Sleep (sem resposta)",
        "detail_compx_sleep_timeout": "Desligado / Sleep (timeout bateria)",
        "detail_compx_sleep_moment": "Desligado / Sleep no momento",
        "detail_compx_usb_no_reply": "Cabo USB conectado (sem resposta)",
        "detail_compx_usb_waiting": "Cabo USB conectado (aguardando leitura)",
        "detail_compx_disconnected": "Receptor 2.4G / cabo USB desconectado",
        "detail_compx_hid_err": "Erro ao consultar HID",
        "detail_xinput_wired": "Slot {slot} - Emulação XInput Wired (nível fixo)",
        "detail_xinput_wireless": "Slot {slot} - XInput Sem Fio ({type_name})",
        "detail_xinput_generic": "Slot {slot} - XInput ({type_name})",
        "detail_xinput_no_bat": "Slot {slot} conectado (XInput sem bateria)",
        "detail_xinput_standby": "Slot {slot} sem bateria / standby",
        "detail_gamepad_sleep": "Receptor conectado (sleep/desligado)",
        "detail_disconnected": "Desconectado",
        "detail_bt_connected": "Conectado via Bluetooth",
        "detail_morcego_no_telemetry": "Conectado 2.4 GHz (dongle USB sem telemetria; conecte via Bluetooth para %)",
        "state_charging": "Carregando",
        "state_xinput_wired": "Emulação XInput Wired",
        "state_bluetooth": "Bluetooth",
        "state_battery": "Bateria",
        "last_prefix": "Última: {pct}%",
        "last_prefix_at": "Última: {pct}% às {when}",
        "tooltip_sleep_last": "{name}: Desligado/Sleep ({last})",
        "tooltip_sleep_move": "{name}: Desligado/Sleep (mova para atualizar)",
        "tooltip_no_telemetry": "{name}: Conectado 2.4G (sem telemetria USB){suffix}",
        "tooltip_disconnected": "{name}: Desconectado (--{suffix})",
        "menu_sleep": "{name}: Desligado/Sleep ({last})",
        # Assistente de primeiro uso
        "setup_title": "Bem-vindo ao HIDPower — Configuração Inicial",
        "setup_desc": "Escolha onde salvar suas configurações e logs. Será criada automaticamente uma subpasta 'HIDPower' dentro do local escolhido.",
        "setup_folder_label": "Pasta de destino:",
        "setup_browse": "Procurar...",
        "setup_preview": "Pasta final do programa: {path}",
        "setup_exe_group": "Executável portátil (HIDPower.exe):",
        "setup_exe_copy": "Copiar HIDPower.exe para a pasta criada (mantém uma cópia na pasta atual)",
        "setup_exe_move": "Mover HIDPower.exe para a pasta criada e remover da pasta atual (recomendado)",
        "setup_exe_keep": "Manter o HIDPower.exe onde está e salvar apenas config/logs na pasta",
        "setup_startup": "Iniciar o HIDPower automaticamente com o Windows",
        "setup_continue": "Continuar",
        "setup_cancel": "Cancelar",
        "setup_err_title": "Erro ao configurar pasta",
        "setup_browse_title": "Escolha a pasta para salvar o HIDPower",
    },
    "en": {
        "app_title": "HIDPower",
        "tab_devices": "Devices",
        "tab_settings": "Settings",
        "tab_pin": "Pin to Taskbar",
        "tab_about": "About",
        # Devices
        "btn_refresh": "Refresh now",
        "btn_hide": "Hide",
        "btn_show": "Show",
        "empty_title": "No compatible wireless peripherals detected right now.",
        "empty_subtitle": "Connect your 2.4 GHz receiver or Bluetooth device and click 'Refresh now'.",
        "card_last_updated": "Last reading: {last}  •  Updated at {updated}",
        "card_sleep_with_pct": "Sleep ({pct}%)",
        "card_sleep": "Sleep",
        "na": "N/A",
        "last_reading_at": "{pct}% at {when}",
        # Settings
        "settings_title": "HIDPower Preferences",
        "settings_language_label": "Idioma / Language:",
        "settings_interval_label": "Refresh interval:",
        "settings_monitor_label": "Display widget on Monitor:",
        "widget_disabled": "Disabled (primary tray only)",
        "widget_monitor_offline": "Disconnected monitor ({device})",
        "btn_reanchor": "Re-anchor",
        "chk_startup": "Start with Windows",
        "chk_hide_unsupported": "Hide devices without USB telemetry in tray (e.g., 2.4 GHz headset without battery HID)",
        "settings_folder_title": "HIDPower data & logs folder",
        "btn_open_folder": "Open folder",
        "btn_run_wizard": "Change folder...",
        # Pin guide
        "pin_heading": "How to keep battery icons always visible next to the network icon",
        "pin_intro": "By default in Windows 11/10, new tray icons start hidden inside the (^) overflow chevron near the clock. You only need to pin them once:",
        "pin_step1_title": "Method 1 — Fastest (drag and drop)",
        "pin_step1_body": (
            "1. Click the (^) chevron on the taskbar next to the clock.\n"
            "2. Drag each Mouse / Gamepad battery icon directly to the space next to the Internet and Sound icons.\n"
            "3. Release the mouse button: the icon will remain pinned there."
        ),
        "pin_step2_title": "Method 2 — Windows 11 Settings",
        "pin_step2_body": (
            "1. Click the blue button below to open Taskbar Settings.\n"
            "2. Expand 'Other system tray icons'.\n"
            "3. Turn on the toggle for 'HIDPower' (or each peripheral icon)."
        ),
        "pin_step3_title": "Note on permanent pinning",
        "pin_step3_body": (
            "Once HIDPower.exe stays in the same folder, Windows remembers the pinned icon positions across restarts."
        ),
        "btn_taskbar_settings": "Open Taskbar Settings",
        "taskbar_err_title": "Taskbar",
        "taskbar_err_msg": (
            "Could not open Windows Settings automatically.\n\n"
            "Open manually: Settings > Personalization > Taskbar > Other system tray icons.\n\n"
            "Details: {err}"
        ),
        # About
        "about_heading": "How HIDPower works under the hood",
        "about_s1_title": "Automatic discovery & Compx dual-mode unification (2.4 GHz + USB)",
        "about_s1_body": (
            "• Compx Mouse (25A7:FA07 / 25A7:FA08): unified into a single tray icon and card. "
            "When plugged in via USB to charge, wired mode (FA08) takes over automatically with "
            "'Charging via USB' and a lightning bolt, suppressing the sleeping 2.4G duplicate.\n"
            "• XInput Controllers (Slots 0..3): queried via xinput1_4.dll (XInputGetBatteryInformation).\n"
            "• Bluetooth Peripherals: queried natively via Windows PnP (cfgmgr32 / DEVPKEY_Bluetooth_Battery)."
        ),
        "about_s2_title": "Color legend, Sleep mode & multi-monitor widget",
        "about_s2_body": (
            "• Green bar (> 20%) | Yellow (11% to 20%) | Red (<= 10%) | Bolt (Charging).\n"
            "• Sleeping mouse: icon stays visible with a 'Z' badge and dimmed bar preserving the last known percentage.\n"
            "• Multi-monitor: enable 'Display widget on Monitor' in Settings to dock a compact dark bar on another monitor's taskbar."
        ),
        "about_s3_title": "Why some 2.4 GHz headsets are hidden automatically",
        "about_s3_body": (
            "• Some USB audio dongles (such as Fallen Morcego Pro Wireless 3206:0881) expose only USB audio and media keys "
            "without USB battery telemetry.\n"
            "• They start hidden in 2.4 GHz mode, and you can toggle visibility anytime using the Hide/Show button."
        ),
        "btn_hid_diag": "View USB (HID) Diagnostics",
        "hid_diag_title": "USB (HID) & Bluetooth Diagnostics",
        # Footer
        "chk_dont_show": "Don't show this window on startup",
        "btn_minimize": "Minimize to Tray",
        # Tray & Widget
        "tray_no_devices": "No devices detected",
        "tray_no_visible": "HIDPower: No visible devices",
        "menu_open_dashboard": "Open Dashboard...",
        "menu_pin_guide": "Pin to taskbar guide...",
        "menu_widget_monitor": "Display widget on Monitor",
        "menu_refresh": "Refresh now",
        "menu_hide_unsupported": "Hide unsupported devices",
        "menu_startup": "Start with Windows",
        "menu_quit": "Quit",
        "menu_reanchor_widget": "Re-anchor widget on taskbar",
        "widget_pos_above": "Position above taskbar",
        "widget_pos_over": "Position over taskbar",
        "widget_reanchor": "Re-anchor to default position",
        "widget_move_monitor": "Move to Monitor",
        "widget_close": "Close widget",
        # Monitors
        "monitor_primary": "Primary",
        "monitor_secondary": "Secondary",
        "monitor_label": "Monitor {index} ({role} — {width}×{height})",
        # Errors / Single instance
        "already_running": "HIDPower is already running in the system tray.",
        "startup_err_title": "Startup Error",
        "startup_err_msg": "Could not update the startup shortcut:\n{err}",
        "startup_tray_err": "Could not update Windows startup setting:\n{err}",
        # Device details & tooltips
        "detail_compx_charging": "Charging via USB",
        "detail_compx_charging_full": "Charging via USB (full)",
        "detail_compx_24g": "Connected 2.4 GHz (10% steps)",
        "detail_compx_sleep": "Off / Sleeping (idle)",
        "detail_compx_sleep_no_reply": "Off / Sleeping (no reply)",
        "detail_compx_sleep_timeout": "Off / Sleeping (battery timeout)",
        "detail_compx_sleep_moment": "Off / Sleeping right now",
        "detail_compx_usb_no_reply": "USB cable connected (no reply)",
        "detail_compx_usb_waiting": "USB cable connected (awaiting reading)",
        "detail_compx_disconnected": "2.4G receiver / USB cable disconnected",
        "detail_compx_hid_err": "HID query error",
        "detail_xinput_wired": "Slot {slot} - XInput Wired emulation (fixed level)",
        "detail_xinput_wireless": "Slot {slot} - XInput Wireless ({type_name})",
        "detail_xinput_generic": "Slot {slot} - XInput ({type_name})",
        "detail_xinput_no_bat": "Slot {slot} connected (XInput no battery)",
        "detail_xinput_standby": "Slot {slot} no battery / standby",
        "detail_gamepad_sleep": "Receiver connected (sleep/off)",
        "detail_disconnected": "Disconnected",
        "detail_bt_connected": "Connected via Bluetooth",
        "detail_morcego_no_telemetry": "Connected 2.4 GHz (USB dongle has no battery telemetry; use Bluetooth for %)",
        "state_charging": "Charging",
        "state_xinput_wired": "XInput Wired emulation",
        "state_bluetooth": "Bluetooth",
        "state_battery": "Battery",
        "last_prefix": "Last: {pct}%",
        "last_prefix_at": "Last: {pct}% at {when}",
        "tooltip_sleep_last": "{name}: Off/Sleep ({last})",
        "tooltip_sleep_move": "{name}: Off/Sleep (move to wake)",
        "tooltip_no_telemetry": "{name}: Connected 2.4G (no USB telemetry){suffix}",
        "tooltip_disconnected": "{name}: Disconnected (--{suffix})",
        "menu_sleep": "{name}: Off/Sleep ({last})",
        # First-run setup wizard
        "setup_title": "Welcome to HIDPower — Initial Setup",
        "setup_desc": "Choose where to store settings and logs. An 'HIDPower' subfolder will be created automatically inside the selected location.",
        "setup_folder_label": "Destination folder:",
        "setup_browse": "Browse...",
        "setup_preview": "Final application folder: {path}",
        "setup_exe_group": "Portable executable (HIDPower.exe):",
        "setup_exe_copy": "Copy HIDPower.exe into the created folder (keeps a copy in current folder)",
        "setup_exe_move": "Move HIDPower.exe into the created folder and remove from current folder (recommended)",
        "setup_exe_keep": "Keep HIDPower.exe in its current location and store only config/logs here",
        "setup_startup": "Start HIDPower automatically with Windows",
        "setup_continue": "Continue",
        "setup_cancel": "Cancel",
        "setup_err_title": "Folder setup error",
        "setup_browse_title": "Select folder for HIDPower",
    },
}


def tr(lang: str, key: str, **kwargs: object) -> str:
    """Retorna string traduzida para o idioma selecionado com fallback seguro."""
    norm = normalize_language(lang)
    table = TRANSLATIONS.get(norm, TRANSLATIONS["pt-BR"])
    template = table.get(key) or TRANSLATIONS["pt-BR"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template
