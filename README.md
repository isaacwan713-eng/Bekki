🩵 Bekki AI

Bekki is a local desktop AI companion created and maintained by YW49. It is built with Python, PySide6, Ollama, and local language models.

It is designed around a simple principle:

AI handles understanding and semantic decisions; Python handles deterministic execution, state, and tools.

Bekki is not just a chat window. It can retain useful context, remember selected user preferences, search the web when needed, read local files, and understand images or screenshots.

V1 features

Local AI chat through Ollama

Conversation context for references such as “that”, “it”, and “today”

Memory for selected profile, preference, relationship, and temporary facts

Web-search pipeline with AI search decisions and evidence passed back to the main model

Local document reader for PDF, DOCX, TXT, MD, CSV, and XLSX

Document overview and retrieval modes, selected by an AI document router

Image and screenshot understanding for PNG, JPG, JPEG, and WEBP

User-triggered Desktop Reading for the primary display, active window, or a selected screenshot region through the local Vision model

In-app thumbnail previews for uploaded images and every Desktop Reading capture

PySide6 desktop interface with file/image attachment cards and live activity status

Windows desktop build through PyInstaller

How Bekki chooses a source

User need

Primary source

Personal preferences or past conversation

Memory / conversation context

Question about the active local document

Document reader

Question about the active image or screenshot

Vision model

Current or changing information

Web search

Document claim that needs current verification

Document reader + web search

Requirements

Windows 10/11

Python 3.10+ for development

Ollama

Pillow (pip install pillow) for Desktop Reading screenshots

NVIDIA GPU recommended for a responsive local experience

The V1 configuration uses these local models:

ollama pull gpt-oss:20b
ollama pull gemma3:27b

gpt-oss:20b handles the main chat workflow. gemma3:27b handles image understanding.

Development setup

git clone <your-repository-url>
cd AI-Assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py

Create a .env file if you want web search:

BRAVE_API_KEY=your_key_here

Keep .env private. Never commit or share it.

Use the Windows app

After packaging, open:

dist\Bekki\Bekki.exe

Keep the full Bekki folder together. The executable needs the bundled assets, prompts, and configuration files beside it.

Build a Windows release

Install PyInstaller once:

pip install pyinstaller

Then build using the project specification:

pyinstaller --noconfirm --clean Bekki.spec

For troubleshooting, temporarily set console=True in Bekki.spec to keep a terminal log visible.

Sharing with another person

Do not send only Bekki.exe; zip and share the entire dist\Bekki folder.

The recipient must install Ollama and download the models themselves. Do not distribute your own .env, because it may contain private API keys. They can create their own .env if they want web search.

V1 limits

One active document at a time

No OCR for image-only PDFs yet

Local-model speed and quality depend on the recipient’s GPU and available VRAM

Vision is single-image analysis, not continuous screen monitoring

Desktop Reading only captures after an explicit click and does not continuously monitor the screen

Search is optional and requires the user’s own Brave Search API key

Project roadmap

V1 — Complete

Reliable local chat, memory, context, search, documents, vision, polished UI, and a Windows desktop build.

V2 — MAGI Core and desktop companion

Single-model MAGI routing, persona/research/reasoning profiles, multi-session chat history, and a state-driven desktop companion.

V3 — Multi-model MAGI

Independent specialist agents, evidence comparison, and a MAGI judge for complex decisions.

Author and ownership

Created and maintained by YW49.

Copyright © 2026 YW49. All rights reserved.