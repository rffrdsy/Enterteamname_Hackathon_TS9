import io
import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

BASE_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGO_PATH  = os.path.join(ASSETS_DIR, "mooOSLogoOnly.png")
TEMPLATE_NAME = "report_template.html"

def generate_report_pdf(report_type: str, period: str, data: dict) -> bytes:
    env = Environment(loader=FileSystemLoader(BASE_DIR))
    template = env.get_template(TEMPLATE_NAME)
    
    logo_file_path = LOGO_PATH.replace('\\', '/')
    
    html_out = template.render(
        report_type=report_type.capitalize(),
        period=period,
        data=data,
        logo_path=logo_file_path if os.path.exists(LOGO_PATH) else None,
        now_str=datetime.now().strftime("%d %B %Y %H:%M")
    )

    buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(
        src=html_out,
        dest=buffer,
        encoding='utf-8'
    )
    if pisa_status.err:
        raise Exception(f"Failed to generate PDF. Error: {pisa_status.err}")

    return buffer.getvalue()
