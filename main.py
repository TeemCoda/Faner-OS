import webview
import os
import json
import base64
import sys
import re
import threading
import mimetypes
from urllib.parse import unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def get_storage_dir():
    # Relative paths like 'user_data' resolve against the CURRENT WORKING
    # DIRECTORY at launch time. For a normal `python main.py` run that's
    # stable, but for a PyInstaller --onefile .exe it's a fresh temp
    # extraction folder every single launch — so anything saved there
    # looks like it "disappears" on next open. Anchor to a real, stable
    # location instead.
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'FanerOS')
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_data')


def make_file_server_handler(root_dir):
    # Serves files straight from disk, streamed in small chunks, with
    # HTTP Range support so <video>/<audio> can seek without ever
    # loading the whole file into memory anywhere. This replaces the
    # old approach of base64-encoding entire files and shipping them
    # through the JS<->Python bridge, which is what was blowing up
    # memory usage on large files.
    class FileServerHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._serve(send_body=False)

        def do_GET(self):
            self._serve(send_body=True)

        def _serve(self, send_body):
            # JS builds URLs with encodeURIComponent(name), so anything with
            # a space or special character arrives here still percent-encoded
            # (e.g. "My%20Photo.jpg"). Without decoding it, a file lookup for
            # the literal encoded name fails — this was breaking any photo or
            # song with a space in its filename, which is most of them.
            filename = unquote(self.path.lstrip('/'))
            filepath = os.path.join(root_dir, filename)
            # Prevent escaping the storage dir via '..' in the path
            if not os.path.abspath(filepath).startswith(os.path.abspath(root_dir)):
                self.send_error(403)
                return
            if not os.path.isfile(filepath):
                self.send_error(404)
                return

            file_size = os.path.getsize(filepath)
            mime_type = mimetypes.guess_type(filepath)[0] or 'application/octet-stream'
            range_header = self.headers.get('Range')

            if range_header:
                m = re.match(r'bytes=(\d+)-(\d*)', range_header)
                start = int(m.group(1)) if m else 0
                end = int(m.group(2)) if (m and m.group(2)) else file_size - 1
                end = min(end, file_size - 1)
                length = max(0, end - start + 1)
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Content-Length', str(length))
            else:
                start = 0
                length = file_size
                self.send_response(200)
                self.send_header('Content-Length', str(file_size))

            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Type', mime_type)
            self.send_header('Access-Control-Allow-Origin', '*')  # lets fetch() read text files too
            self.end_headers()

            if not send_body:
                return

            with open(filepath, 'rb') as f:
                f.seek(start)
                remaining = length
                chunk_size = 64 * 1024
                while remaining > 0:
                    data = f.read(min(chunk_size, remaining))
                    if not data:
                        break
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                        # Normal when a browser cancels an in-flight request —
                        # e.g. seeking in a video, or switching tracks before
                        # the previous one finished loading. Not a real error.
                        break
                    remaining -= len(data)

        def log_message(self, format, *args):
            pass  # silence per-request console spam

    return FileServerHandler


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # By default, socketserver prints a full traceback to stderr for
        # ANY exception during a request — including totally routine
        # client disconnects (a browser cancelling a video request mid-
        # seek, switching tracks before the old request finished, etc).
        # Those happen constantly during normal playback, so silence
        # just those and let anything genuinely unexpected still print.
        exc_type = sys.exc_info()[0]
        if exc_type in (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        super().handle_error(request, client_address)


class Api:
    def __init__(self):
        self.storage_dir = get_storage_dir()
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

        # Start the local file server on a random free port, in the
        # background, for the lifetime of the app.
        handler_cls = make_file_server_handler(self.storage_dir)
        self.httpd = QuietThreadingHTTPServer(('127.0.0.1', 0), handler_cls)
        self.server_port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def get_server_port(self):
        return self.server_port

    def _safe_filename(self, name):
        # Strip any path components — a filename should never be able to
        # escape the storage directory (e.g. "../../something" or an
        # absolute path). Keep only the actual filename part.
        return os.path.basename(name.replace('\\', '/'))

    def save_file(self, name, base64_data):
        # Still used for saving files coming FROM the browser (drag-and-drop
        # gives JS a File object, and JS is the only side that has it) —
        # that direction still has to cross the bridge somehow. It's
        # reading large files back out that we've now made cheap.
        try:
            safe_name = self._safe_filename(name)
            if not safe_name:
                return "Invalid filename"
            if ',' in base64_data: base64_data = base64_data.split(',')[1]
            data = base64.b64decode(base64_data)
            final_path = os.path.join(self.storage_dir, safe_name)
            tmp_path = final_path + '.part'
            # Write to a temp file first, then atomically rename into place.
            # Without this, the file server (running concurrently on its
            # own thread) could serve a half-written file to anything
            # requesting it mid-save — a real cause of "corrupted" reads.
            with open(tmp_path, 'wb') as f:
                f.write(data)
            os.replace(tmp_path, final_path)
            return True
        except Exception as e: return str(e)

    def list_files(self):
        return [f for f in os.listdir(self.storage_dir) if not f.endswith('.part')]

    def delete_file(self, name):
        try:
            os.remove(os.path.join(self.storage_dir, self._safe_filename(name)))
            return True
        except: return False

    def save_setting(self, key, value):
        settings = self.load_settings()
        settings[key] = value
        final_path = os.path.join(self.storage_dir, 'settings.json')
        tmp_path = final_path + '.tmp'
        # Same atomic write-then-rename pattern as save_file — otherwise
        # an interrupted write leaves corrupt JSON, and load_settings()
        # would then fail on every single future launch until someone
        # manually deletes the file.
        with open(tmp_path, 'w') as f:
            json.dump(settings, f)
        os.replace(tmp_path, final_path)

    def load_settings(self):
        path = os.path.join(self.storage_dir, 'settings.json')
        if not os.path.exists(path): return {}
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # Corrupt or unreadable settings file — recover instead of
            # breaking every future launch. Keep the broken file around
            # (renamed) in case it's ever worth a look, rather than just
            # silently deleting someone's settings.
            print("settings.json was corrupt, resetting:", e)
            try:
                os.replace(path, path + '.corrupt')
            except OSError:
                pass
            return {}

    def get_file_list(self):
        return [f for f in os.listdir(self.storage_dir) if not f.endswith('.part')]

    def read_file(self, filename):
        path = os.path.join(self.storage_dir, self._safe_filename(filename))
        with open(path, 'r', errors='ignore') as f:
            return f.read()

    def read_file_base64(self, filename):
        # Kept for anything still using it, but the file server is now
        # the preferred path for anything of meaningful size.
        path = os.path.join(self.storage_dir, filename)
        with open(path, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode('utf-8')

    def open_file_dialog(self):
        result = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN)
        if result:
            return result[0]
        return None

    def import_files(self):
        import shutil
        paths = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        if not paths:
            return []
        added = []
        for p in paths:
            try:
                dest = os.path.join(self.storage_dir, os.path.basename(p))
                shutil.copy(p, dest)
                added.append(os.path.basename(p))
            except Exception as e:
                print("Import failed for", p, e)
        return added

    def purge_all(self):
        try:
            for f in os.listdir(self.storage_dir):
                if f == 'settings.json':
                    continue
                os.remove(os.path.join(self.storage_dir, f))
            return True
        except Exception as e:
            return str(e)

    def close_app(self):
        webview.windows[0].destroy()

    def shutdown_system(self):
        # import subprocess
        # subprocess.run(['shutdown', '/s', '/t', '0'])  # Windows only
        pass


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


if __name__ == '__main__':
    api = Api()
    window = webview.create_window(
        'Faner OS',
        resource_path('faner_os3.html'),
        js_api=api,
        width=1280,
        height=800,
        min_size=(800, 600),
        fullscreen=True
    )
    webview.start()