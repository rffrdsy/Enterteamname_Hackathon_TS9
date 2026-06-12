"""
spk_generator.py
Generate PDF "Surat Keterangan Jual Beli Ternak" menggunakan HTML-to-PDF (Jinja2 + xhtml2pdf).
"""

import io
import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

# ─────────────────────────────────────────────────────────────
# Path aset
# ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGO_PATH  = os.path.join(ASSETS_DIR, "mooOSLogoOnly.png")
TEMPLATE_NAME = "spk_template.html"

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _s(val) -> str:
    """Konversi None / apapun ke string aman."""
    if val is None:
        return "-"
    return str(val).strip() or "-"


def _label_status(status: str) -> str:
    mapping = {
        "LOOKING_FOR_CARETAKER": "Menunggu Verifikasi",
        "AVAILABLE":             "Aktif",
        "REJECTED":              "Non-Aktif",
        "PREGNANT":              "Bunting",
        "SICK":                  "Sakit",
        "DEAD":                  "Mati",
        "WAITING_CONFIRMATION":  "Menunggu Konfirmasi",
        "SOLD":                  "Terjual",
    }
    return mapping.get(status or "", status or "-")


def _bulan_id(n: int) -> str:
    bulan = [
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    return bulan[n] if 1 <= n <= 12 else str(n)


def _fmt_tgl(raw: str) -> str:
    """Format ISO date ke 'DD Bulan YYYY'."""
    if not raw or raw == "-":
        return "-"
    try:
        dt = datetime.fromisoformat(raw)
        return f"{dt.day} {_bulan_id(dt.month)} {dt.year}"
    except Exception:
        return raw


def _now_id() -> str:
    now = datetime.now()
    return f"{now.day} {_bulan_id(now.month)} {now.year}"


# ─────────────────────────────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────────────────────────────
def generate_spk_pdf(cow_data: dict) -> bytes:
    """
    Terima dict cow_data, kembalikan bytes PDF surat resmi.

    Keys: cow_code, owner_name, jenis, umur, weight,
          tgl_masuk, status, deskripsi, foto_path
    """
    now_str = _now_id()
    cow_code   = _s(cow_data.get("cow_code"))
    owner_name = _s(cow_data.get("owner_name"))
    jenis      = _s(cow_data.get("jenis"))
    umur       = _s(cow_data.get("umur"))
    weight     = cow_data.get("weight")
    berat_str  = f"{weight:.1f} kg" if weight else "-"
    tgl_masuk  = _fmt_tgl(cow_data.get("tgl_masuk") or "")
    status_raw = cow_data.get("status") or ""
    status_lbl = _label_status(status_raw)
    deskripsi  = str(cow_data.get("deskripsi") or "").strip()
    foto_path  = cow_data.get("foto_path") or ""

    doc_no = (
        f"{datetime.now().strftime('%Y%m%d')}"
        f"/{cow_code.replace('-', '').replace(' ', '')}"
        f"/KOP-MOOOS/SJBT"
    )

    # Siapkan environment Jinja2
    env = Environment(loader=FileSystemLoader(BASE_DIR))
    template = env.get_template(TEMPLATE_NAME)

    # Convert logo path for HTML (xhtml2pdf supports local absolute paths well)
    # We use file:// prefix for Windows absolute paths just in case, but xhtml2pdf usually accepts raw paths.
    logo_file_path = LOGO_PATH.replace('\\', '/')

    # Render template dengan data sapi
    html_out = template.render(
        now_str=now_str,
        doc_no=doc_no,
        cow_code=cow_code,
        owner_name=owner_name,
        jenis=jenis,
        umur=umur,
        berat_str=berat_str,
        tgl_masuk=tgl_masuk,
        status_lbl=status_lbl,
        deskripsi=deskripsi,
        logo_path=logo_file_path if os.path.exists(LOGO_PATH) else None,
        now_year=datetime.now().year
    )

    # Generate PDF menggunakan xhtml2pdf
    buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(
        src=html_out,           # HTML string
        dest=buffer,            # Output buffer
        encoding='utf-8'
    )

    if pisa_status.err:
        raise Exception(f"Failed to generate PDF. Error: {pisa_status.err}")

    return buffer.getvalue()
