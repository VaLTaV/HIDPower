<p align="center">
  <img src="assets/logo.png" alt="HIDPower Logo" width="760">
</p>

<p align="center">
  <a href="#english">English</a> •
  <a href="#português-brasil">Português (Brasil)</a>
</p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0ea5e9?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12%2B-3b82f6?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square">
</p>

---

## English

**HIDPower** is a lightweight, standalone Windows 10/11 system tray battery monitor for wireless peripherals connected via **2.4 GHz USB dongles**, **XInput**, and **Bluetooth** — without bloated vendor suites.

### Key Features
- **Automatic Multi-Protocol Discovery:**
  - **Unified Compx / Areson Dual-Mode (`0x25A7:0xFA07` 2.4 GHz + `0x25A7:0xFA08` USB Cable):** Queries online (`cmd 0x03`) and battery (`cmd 0x04`) via HID (`0xFF01` / `0xFF02`) without waking an idle mouse. Plugging in the USB cable (`FA08`) seamlessly merges into a single **"Charging via USB"** icon/card and suppresses the sleeping 2.4 GHz duplicate.
  - **XInput Controllers (Slots `0..3`):** Native battery polling via `xinput1_4.dll` (`ctypes`), plus HID dongle standby presence detection (e.g. `HORI / SHANWAN`).
  - **Bluetooth Peripherals (Native PnP):** Reads any paired Bluetooth mouse, keyboard, gamepad, or headset reporting `DEVPKEY_Bluetooth_Battery` via `cfgmgr32.dll`.
- **Dynamic Vector Tray Icons (`64×64` RGBA in memory):**
  - Peripheral silhouette + proportional vertical battery bar (**Green** `> 20%`, **Yellow** `11%–20%`, **Red** `<= 10%`, **Lightning Bolt** when charging, and **Sleep `Z` badge** keeping the last known reading).
- **Per-Device Hide / Show & Flicker-Free UI:**
  - In-place Tkinter updates (zero card flicker) with a dedicated **Hide / Show** button per device card and a clean **Settings** tab.
- **Multi-Monitor Taskbar Widget:**
  - Dock a compact, dark, always-on-top mini-bar directly on a secondary monitor's taskbar (`EnumDisplayMonitors` + Per-Monitor V2 DPI scaling via `ctypes`), with free drag-and-drop and right-click context menu.
- **Bilingual UI & Portable First-Run Wizard:**
  - Instant switching between **Português (Brasil)** and **English**.
  - Standalone `HIDPower.exe`: on first launch, choose where to create your portable `HIDPower` folder (`config.json`, `state.json`, `hidpower.log`), optionally copy or move `HIDPower.exe` there, and enable **Start with Windows**.

### Download (GitHub Releases)
1. Download the latest **`HIDPower.exe`** from the **Releases** page.
2. Double-click **`HIDPower.exe`**.
3. Follow the first-run folder setup wizard to create your portable `HIDPower` folder and start monitoring.

### Build from Source
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run live self-test & tray smoke test
python battery_tray.py --self-test
python battery_tray.py --smoke-tray 3

# Build standalone executable (no console, no .ico)
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --noconsole --onefile --name "HIDPower" battery_tray.py
```

---

## Português (Brasil)

**HIDPower** é um monitor leve e autônomo para **Windows 10/11** que exibe na bandeja do sistema a bateria de periféricos sem fio via **receptores USB 2.4 GHz**, **XInput** e **Bluetooth** — sem precisar instalar suítes pesadas de fabricantes.

### Principais Recursos
- **Descoberta Automática Multi-Protocolo:**
  - **Mouse Compx Unificado (`0x25A7:0xFA07` 2.4 GHz + `0x25A7:0xFA08` Cabo USB):** Consulta estado online (`cmd 0x03`) e nível de bateria (`cmd 0x04`) via HID (`0xFF01` / `0xFF02`) sem acordar o mouse em modo sleep. Ao conectar o cabo USB (`FA08`), unifica automaticamente em um único ícone/card **"Carregando via USB"** com raio e oculta a duplicata 2.4 GHz em sleep.
  - **Controles XInput (Slots `0..3`):** Consulta nativa via `xinput1_4.dll` (`ctypes`), além de detectar presença de receptores HID compatíveis (`HORI / SHANWAN`).
  - **Dispositivos Bluetooth (PnP nativo):** Consulta qualquer headset, mouse, teclado ou controle pareado que exponha `DEVPKEY_Bluetooth_Battery` via `cfgmgr32.dll`.
- **Ícones Vetoriais Dinâmicos (`64×64` RGBA em memória):**
  - Silhueta do periférico + barra vertical colorida (**Verde** `> 20%`, **Amarela** `11%–20%`, **Vermelha** `<= 10%`, **Raio** carregando e **marca `Z`** em Sleep preservando a última porcentagem lida).
- **Botão Ocultar / Exibir por Dispositivo e Painel sem Flicker:**
  - Atualização **in-place** dos cards (zero piscar) com botão compacto **Ocultar / Exibir** na bandeja em cada periférico e aba dedicada **Configurações**.
- **Widget na Barra de Tarefas de Outro Monitor:**
  - Exibe uma mini-barra discreta e sempre visível diretamente na barra de tarefas do monitor secundário (`EnumDisplayMonitors` + DPI Per-Monitor V2 via `ctypes`), com arraste livre e menu de contexto.
- **Interface Bilíngue e Assistente Portátil:**
  - Alternância instantânea entre **Português (Brasil)** e **English**.
  - Executável único `HIDPower.exe`: no primeiro uso, escolha onde criar a pasta portátil `HIDPower` (`config.json`, `state.json`, `hidpower.log`), copie ou mova o `.exe` automaticamente e configure **Iniciar com o Windows**.

### Download (GitHub Releases)
1. Baixe o **`HIDPower.exe`** mais recente na aba **Releases**.
2. Execute o **`HIDPower.exe`**.
3. Escolha a pasta de destino no assistente inicial para criar sua pasta `HIDPower` e iniciar o monitoramento.

### Compilação Local
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Executar aplicativo sem janela de terminal
.\.venv\Scripts\pythonw.exe .\battery_tray.py

# Compilar executável único (sem console e sem .ico)
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --noconsole --onefile --name "HIDPower" battery_tray.py
```

---

## Project Structure / Estrutura

- `battery_tray.py` — Main entry point, tray multi-icon orchestrator, polling & CLI
- `battery_readers.py` — Hardware discovery & readers (Unified Compx `FA07`/`FA08`, XInput, Bluetooth PnP)
- `ui_window.py` — Flicker-free Tkinter dashboard (`Devices`, `Settings`, `Pin to Taskbar`, `About`)
- `taskbar_widget.py` — Secondary-monitor taskbar mini-bar widget
- `monitor_utils.py` — Native Win32 monitor enumeration, Per-Monitor V2 DPI & window styles (`ctypes`)
- `setup_wizard.py` — Portable first-run folder & executable setup wizard
- `app_config.py` — Portable `HIDPower` folder resolution, JSON config/cache, logs & `shell:startup`
- `icon_renderer.py` — 4× supersampled in-memory RGBA icons, `H I P` emblem & PNG banner generator
- `i18n.py` — Full `pt-BR` / `en` localization dictionary
- `scanner_usb.py` / `probe_dispositivos.py` — Passive HID discovery and diagnostics helpers

---

## License / Licença

MIT License — see [LICENSE](LICENSE).
