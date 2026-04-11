import json
from pathlib import Path
import pdfkit


def render_pdf(month):

    base = Path(__file__).resolve().parent

    input_file = base / "output" / f"{month}_analysis.json"
    output_file = base / "pdf" / f"{month}_NOTHS_report.pdf"

    output_file.parent.mkdir(exist_ok=True)

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    html = f"""
    <html>
    <head>
    <style>
    body {{
        font-family: Arial;
        padding: 40px;
        line-height: 1.6;
    }}
    h1 {{ font-size: 26px; }}
    h2 {{ margin-top: 30px; }}
    li {{ margin-bottom: 6px; }}
    </style>
    </head>
    <body>

    <h1>NOTHS Top Product Intelligence</h1>
    <h2>{month}</h2>

    <h3>Summary</h3>
    <p>{data.get("summary","")}</p>

    <h3>Strong Patterns</h3>
    <ul>
    {''.join(f"<li>{x}</li>" for x in data.get("strong_patterns",[]))}
    </ul>

    <h3>Weaker Patterns</h3>
    <ul>
    {''.join(f"<li>{x}</li>" for x in data.get("weaker_patterns",[]))}
    </ul>

    <h3>Exceptions</h3>
    <ul>
    {''.join(f"<li>{x}</li>" for x in data.get("exceptions",[]))}
    </ul>

    <h3>Seller Takeaways</h3>
    <ul>
    {''.join(f"<li>{x}</li>" for x in data.get("seller_takeaways",[]))}
    </ul>

    </body>
    </html>
    """

    # IMPORTANT: set your wkhtmltopdf path here
    config = pdfkit.configuration(
        wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
    )

    pdfkit.from_string(
        html,
        str(output_file),
        configuration=config
    )

    print(f"PDF saved to: {output_file}")


if __name__ == "__main__":
    render_pdf("2026-03")
