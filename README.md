# Faner OS

A desktop environment that boots inside a browser tab - built with HTML, CSS, and vanilla JavaScript on the front end, with a lightweight Python backend (via [pywebview](https://pywebview.flowrl.com/)) handling real file storage, a local streaming file server, and native OS dialogs.

Every "app" in Faner OS is just HTML rendered into a window - no build step, no framework. Windows drag, resize, minimize, and maximize like a real desktop, and the whole thing persists your files, wallpaper, and settings across restarts.

## Features

- **Window manager** - draggable, resizable windows with focus stacking and a taskbar
- **Persistent storage** - files, wallpaper, and settings survive restarts, saved to a per-user app data folder
- **Local streaming file server** - video and audio stream directly from disk (with seek support) instead of being loaded into memory
- **Sandbox** - a virtual file system you can drop files into, browse, and delete
- **Built-in apps** - Tunez (music player), Videos, Notes, PDF viewer ("Horse"), Gallery, Sticky Notes, Finder (searches your own files), Rocket Browser (embedded Wikipedia browsing)
- **Install HTML apps** - drop any `.html` file onto the desktop and it becomes a real launchable app
- **Customizable** - taskbar color, background dim, wallpaper (including tiled mode), font, and theme presets, all in Settings
- **A boot animation** on launch

## Running it

**Requirements:** Python 3, and the packages in the imports at the top of `main.py` (`pywebview` is the main one - install with `pip install pywebview`).

```
python main.py
```

## Building a standalone .exe (Windows)

```
python -m pip install pyinstaller
python -m PyInstaller --onefile --add-data "faner_os3.html;." --add-data "icons;icons" --add-data "fonts;fonts" main.py
```

The built executable will be in `dist/`.

## Project structure

```
main.py           - Python backend: storage, local file server, native dialogs, window creation
faner_os3.html     - the entire OS: UI, window manager, and every built-in app
icons/             - app icons
fonts/             - bundled VT323 font (avoids depending on Google Fonts at runtime)
```

## Status

Actively being built. Current focus: exploring bundling it into a minimal custom Linux distro (Alpine-based) as a kiosk-style boot target.
