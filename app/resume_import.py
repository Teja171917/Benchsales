"""Resume folder import: the website reads resumes from a Google Drive folder
by itself, so nobody has to press "Add resumes" for every consultant.

Setup (once): put the resumes in one Drive folder, share it as "Anyone with
the link can view", and paste the folder link and a free Google API key in
Settings. After that, new or changed files are picked up automatically.

Only files directly inside that one folder are read. Nothing is ever written
to or deleted from Drive. Resumes are stored in this app's own database only.
"""
import re

import requests

from app import db

API = "https://www.googleapis.com/drive/v3"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GDOC = "application/vnd.google-apps.document"
READABLE = {"application/pdf": ".pdf", DOCX: ".docx", "text/plain": ".txt",
            GDOC: ".docx"}      # a Google Doc is exported as .docx
MAX_FILES_LISTED = 300
MAX_BYTES = 10 * 1024 * 1024
FILES_PER_RUN = 25              # keeps one run short; the rest wait for the next
TIMEOUT = 30

_ID_RES = [re.compile(r"/folders/([A-Za-z0-9_-]{10,})"),
           re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})")]


def folder_id(text: str) -> str:
    """Folder id from a Drive folder link (or a bare id)."""
    text = (text or "").strip()
    for rx in _ID_RES:
        m = rx.search(text)
        if m:
            return m.group(1)
    return text if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text) else ""


class DriveError(Exception):
    pass


def _get(url: str, params: dict, key: str, stream: bool = False):
    try:
        r = requests.get(url, params={**params, "key": key}, timeout=TIMEOUT,
                         stream=stream)
    except requests.RequestException as e:
        raise DriveError(f"could not reach Google Drive: {e.__class__.__name__}")
    if r.status_code in (400, 403) and "key" in r.text.lower():
        raise DriveError("Google rejected the API key (check the key and that "
                         "the Google Drive API is enabled for it)")
    if r.status_code == 404:
        raise DriveError("folder not found - share it as 'Anyone with the link "
                         "can view' and check the link")
    if r.status_code >= 400:
        raise DriveError(f"Google Drive said HTTP {r.status_code}")
    return r


def list_folder(fid: str, key: str) -> list:
    out, token = [], ""
    while len(out) < MAX_FILES_LISTED:
        params = {"q": f"'{fid}' in parents and trashed=false",
                  "fields": "nextPageToken,files(id,name,mimeType,md5Checksum,"
                            "modifiedTime,size)",
                  "pageSize": 100, "supportsAllDrives": "true",
                  "includeItemsFromAllDrives": "true"}
        if token:
            params["pageToken"] = token
        data = _get(f"{API}/files", params, key).json()
        out.extend(data.get("files", []))
        token = data.get("nextPageToken") or ""
        if not token:
            break
    return out[:MAX_FILES_LISTED]


def _version(f: dict) -> str:
    return f.get("md5Checksum") or f.get("modifiedTime") or ""


def download(f: dict, key: str) -> bytes:
    if f["mimeType"] == GDOC:
        r = _get(f"{API}/files/{f['id']}/export", {"mimeType": DOCX}, key, True)
    else:
        r = _get(f"{API}/files/{f['id']}", {"alt": "media"}, key, True)
    data = b""
    for chunk in r.iter_content(65536):
        data += chunk
        if len(data) > MAX_BYTES:
            raise ValueError("file too large (10 MB max)")
    return data


def _file_name(f: dict) -> str:
    name = f.get("name") or "resume"
    ext = READABLE[f["mimeType"]]
    return name if name.lower().endswith(ext) else name + ext


# ---- remembered files (so each resume is read once) ----
def _done(file_id: str):
    with db.get_conn() as conn:
        r = conn.execute("SELECT version FROM imported_files WHERE file_id=?",
                         (file_id,)).fetchone()
    return r["version"] if r else None


def _remember(f, status, consultant_id=None, error=""):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO imported_files(file_id, name, version, status, "
            "consultant_id, error, imported_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(file_id) DO UPDATE SET name=excluded.name, "
            "version=excluded.version, status=excluded.status, "
            "consultant_id=excluded.consultant_id, error=excluded.error, "
            "imported_at=excluded.imported_at",
            (f["id"], f.get("name", ""), _version(f), status, consultant_id,
             error[:300], db.now_iso()))
        conn.commit()


def run(ingest, settings: dict | None = None, files_per_run: int = FILES_PER_RUN) -> dict:
    """Read new/changed resumes from the folder. `ingest(filename, data, kick)`
    adds one resume (it is the same code the Add resumes button uses) and
    returns a dict with name/created/new_matches. Never raises."""
    s = settings or db.get_settings()
    fid = folder_id(s.get("resume_folder_url", ""))
    key = (s.get("google_api_key") or "").strip()
    out = {"added": [], "updated": [], "failed": [], "skipped": 0,
           "waiting": 0, "error": ""}
    if not fid or not key:
        out["error"] = "not set up: add the folder link and Google API key in Settings"
        return out
    try:
        files = list_folder(fid, key)
    except DriveError as e:
        out["error"] = str(e)
        return out
    todo = []
    for f in files:
        if f.get("mimeType") not in READABLE:
            out["skipped"] += 1          # folders, images, .doc, spreadsheets...
        elif _done(f["id"]) != _version(f):
            todo.append(f)
    out["waiting"] = max(0, len(todo) - files_per_run)
    batch = todo[:files_per_run]
    for i, f in enumerate(batch):
        name = _file_name(f)
        try:
            data = download(f, key)
        except (DriveError, ValueError) as e:     # try again next time
            out["failed"].append(f"{name}: {e}")
            continue
        try:
            r = ingest(name, data, i == len(batch) - 1)   # search jobs once, at the end
        except Exception as e:                    # unreadable file: do not retry it forever
            detail = getattr(e, "detail", None) or str(e)
            _remember(f, "error", error=str(detail))
            out["failed"].append(f"{name}: {detail}")
            continue
        _remember(f, "ok", consultant_id=r.get("consultant_id"))
        (out["added"] if r.get("created") else out["updated"]).append(
            {"name": r.get("name", ""), "file": name,
             "new_matches": r.get("new_matches", 0)})
    return out
