from reportlab.pdfgen import canvas
from pypdf import PdfReader

from oraculo_ingest.catalog import _sections, _visual_heading
from oraculo_ingest.catalog_layout import page_lines


def test_layout_reads_left_column_before_right(tmp_path):
    pdf = tmp_path / "columns.pdf"
    document = canvas.Canvas(str(pdf), pagesize=(524, 780))
    document.drawString(45, 700, "ESQUERDA inicio")
    document.drawString(45, 100, "ESQUERDA fim")
    document.drawString(280, 700, "DIREITA inicio")
    document.drawString(280, 100, "DIREITA fim")
    document.save()
    lines = [line["text"] for line in page_lines(PdfReader(str(pdf)).pages[0])]
    assert lines == ["ESQUERDA inicio", "ESQUERDA fim", "DIREITA inicio", "DIREITA fim"]


def test_visual_heading_patterns_are_specific_to_category_and_font():
    skill = {"text": "COMBATE CORPO-A-CORPO", "heading": "COMBATE", "heading_size": 24}
    assert _visual_heading(66, skill) == ("skill", "Combate Corpo-A-Corpo", "")
    advantage = {"text": "AGARRAR RÁPIDO COMBATE", "heading": "AGARRAR RÁPIDO COMBATE",
                 "heading_size": 14}
    assert _visual_heading(78, advantage) == ("advantage", "Agarrar Rápido", "combate")
    modifier = {"text": "BASEADO EM AGARRAR -1 POR GRADUAÇÃO",
                "heading": "BASEADO EM AGARRAR", "heading_size": 14}
    assert _visual_heading(141, modifier) == ("modifier_flaw", "Baseado Em Agarrar", "")
    assert _visual_heading(141, {**modifier, "heading_size": 13}) is None


def test_advantage_summary_tables_do_not_enter_descriptions():
    def line(text, heading="", size=0, y=500):
        return {"text": text, "heading": heading, "heading_size": size, "y": y}

    pages = [{"page": number, "text": ""} for number in (78, 79, 80, 81)]
    visual = {
        78: [line("AÇÃO EM MOVIMENTO COMBATE", "AÇÃO EM MOVIMENTO COMBATE", 14),
             line("Mova-se antes e depois da ação.")],
        79: [line("VANTAGENS DE COMBATE", "VANTAGENS DE COMBATE", 17),
             line("VANTAGEM EFEITO"),
             line("ARMA IMPROVISADA COMBATE", "ARMA IMPROVISADA COMBATE", 14),
             line("Use armas improvisadas.")],
        80: [line("VANTAGENS DE PERÍCIA", "VANTAGENS DE PERÍCIA", 17),
             line("Resumo tabular")],
        81: [line("ATAQUE ACURADO COMBATE", "ATAQUE ACURADO COMBATE", 14, 700),
             line("Acerte com mais precisão.", y=650),
             line("ARTES MARCIAIS E ESTILOS DE LUTA", y=300),
             line("Quadro lateral", y=250)],
    }
    rows = _sections(pages, "hash", "example", visual)
    assert [row["name"] for row in rows] == ["Ação Em Movimento", "Arma Improvisada", "Ataque Acurado"]
    assert all("Resumo tabular" not in row["text"] and "Quadro lateral" not in row["text"]
               for row in rows)
