# MJ AI Desktop Assistant

AI-powered Windows desktop assistant with animated companion, voice interaction, and desktop automation.

## Overview

MJ AI is a lightweight, privacy-first desktop assistant that allows natural conversation with your computer through voice commands and a visual companion. It runs locally without requiring cloud APIs and is designed to work efficiently on laptops with 12GB RAM.

## Features

- **Animated Companion**: Hand-drawn horned imp with bat wings, crossed swords, and expressive states
- **Voice Interaction**: Click-to-toggle microphone with speech-to-text and text-to-speech
- **Local AI**: Ollama integration for running small language models locally
- **Desktop Automation**: Open applications, manage windows, type and click
- **Screen Understanding**: OCR-based text extraction and summarization
- **Multi-step Tasks**: Plan and execute complex workflows
- **File Management**: Safe file operations with user confirmation
- **Persistent Memory**: Local conversation history and preferences
- **Resource Management**: Minimal idle usage, intelligent model loading/unloading
- **Privacy**: All processing happens locally, no cloud dependencies for core features

## System Requirements

- Windows 10 or Windows 11
- 12GB RAM (minimum)
- Modern Intel or AMD processor
- Python 3.10 or higher
- Additional storage for downloaded AI and speech models

## Installation

### Prerequisites
1. Install Python 3.10 or newer.
2. Install [Ollama](https://ollama.ai/) to run a local AI model.
3. For screen text extraction, install the Tesseract OCR application. MJ AI detects it on `PATH` and in common Windows installation folders.
4. Connect a microphone for voice input. Click the microphone to start listening and click it again to submit; voice input stays disabled until permission is granted.

### Installing MJ AI
```bash
# Install Python dependencies
pip install -r requirements.txt

# Pull a small language model for Ollama
ollama pull llama3.2:1b  # or another compatible small model

# Run from the project folder
python run_mj_ai.py
```

#### Windows PowerShell

From the project folder, use the project virtual environment explicitly:

```powershell
& .\.venv\Scripts\python.exe .\run_mj_ai.py
```

If PowerShell is not already in the project folder, run these as two separate
commands (or keep the semicolon between them on one line):

```powershell
Set-Location -LiteralPath 'D:\OneDrive\Desktop\Gareeb AI'
& .\.venv\Scripts\python.exe .\run_mj_ai.py
```

## Usage

1. **Launch**: Run `python run_mj_ai.py` from the project folder, or use the PowerShell command above. MJ AI starts as a small floating companion.
2. **Open chat**: Click the face to open the assistant panel. Drag the companion to move it. Use **Ctrl+Shift+H** or the system tray to show or hide it.
3. **Voice Commands**: Click the microphone button, speak, then click it again to submit. **Ctrl+Shift+M** toggles listening from the keyboard.
4. **Examples**:
   - "Open Chrome"
   - "Explain what's on my screen"
   - "Create a summary of this document"
   - "Switch to VS Code"

### Voice troubleshooting

- In **Settings → Voice**, choose the language you will speak. English is the
  default; Auto-detect is available when you regularly switch languages.
- Click the microphone once to start recording, then click again to stop and submit.
  Very short recordings are rejected with a message instead of being sent as
  likely misheard commands.
- If MJ transcribes your words but does not answer, start Ollama from the
  Windows Start menu. If needed, run `ollama serve` in a separate PowerShell
  window and confirm the configured Ollama URL in **Settings → AI**.
- Check the installed model with `ollama list`. If `llama3.2:1b` is missing,
  install it with `ollama pull llama3.2:1b`.
- Model tags are exact: `llama3.2:latest` is not the same as
  `llama3.2:1b`. For the 1B model, MJ AI requires about 2.5 GB of free system
  resources before it starts inference; close memory-heavy apps if it reports
  that resources are low.

## Configuration

Open the settings panel (Ctrl+, or from the system tray) to configure:
- AI model selection
- Voice settings (speed, volume)
- Microphone permissions
- Screen capture permissions
- Animation preferences
- Memory retention
- Startup behavior

Local model inference and speech recognition use up to 80% of the configured CPU
thread budget by default (up from 50%) to improve response times. Existing
default configurations are migrated automatically; custom CPU budgets are kept.

Configuration, logs, screenshots, and conversation memory are stored under
`%LOCALAPPDATA%\Gareeb AI` on Windows, independent of the folder used to launch
the app. Set the `MJAI_HOME` environment variable before launch to use a
different data directory.

## Key Features Workflow

### Example: Multi-step Task
"Open Notepad, write a summary about AI assistants, and save as notes.txt in Documents"

1. **Parse**: Understand the request and identify steps
2. **Prepare**: Generate the content text
3. **Confirm**: Ask about save location if ambiguous
4. **Execute**: Open Notepad, type content, save
5. **Verify**: Check if file was created successfully
6. **Report**: Confirm completion to user

## Development

### Structure
```
run_mj_ai.py       # Stable launcher
src/
├── core/          # App lifecycle, paths, config, memory, permissions, planner
├── services/      # AI, audio, automation, screen analysis, tool dispatch
├── ui/            # Companion window, conversation panel, settings dialog
└── utils/         # File validation and operations
```

### Key Modules

- **Core**: Main application lifecycle, resource monitoring, configuration
- **AI Service**: Model loading, inference, conversation management
- **Audio Service**: Speech recognition, text-to-speech, voice command processing
- **Automation Service**: Application control, mouse/keyboard simulation
- **Screen Analyzer**: Screenshot capture, OCR, content summarization
- **UI**: Main window, companion widget, settings dialog

### Testing

Install development tools if needed:
```bash
pip install -r requirements-dev.txt
```

Run tests with:
```bash
pytest tests/
```

## Building

The application can be packaged with PyInstaller (install it first with `pip install pyinstaller`):
```bash
pyinstaller --onefile --windowed --paths src --name "MJ AI" run_mj_ai.py
```

## License

This project uses free and open-source software. All dependencies are open-source.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Implement your changes
4. Test thoroughly
5. Submit a pull request

## Support

For issues and support, please check the documentation or submit an issue in the repository.
