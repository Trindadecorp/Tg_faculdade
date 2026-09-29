"""Testes do parser de .eml — dez casos exigidos pelo protocolo de coleta.

Cada teste constrói um .eml artificial, roda o parser e verifica uma garantia
específica. Nenhum dado real é usado.

Uso (a partir de ml/):
    python -m pytest tests/test_eml_parser.py -v
"""
import hashlib
from email.message import EmailMessage

import pytest

from src.corpus.anonimizacao import anonimizar
from src.corpus.eml_parser import PENDENTES_CURADORIA, parse_eml, processar_lote
from src.corpus.schema import calcular_hash


def escrever_eml(pasta, nome: str, *, assunto="Assunto de teste",
                 de="remetente@exemplo.com.br", para="destino@exemplo.com",
                 texto=None, html=None, anexos=None) -> "Path":  # noqa: F821
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = de
    msg["To"] = para
    msg["Date"] = "Mon, 28 Sep 2026 10:00:00 -0300"
    msg["Message-ID"] = "<abc123@exemplo.com.br>"
    msg["Received"] = "from mail.exemplo.com.br (192.168.1.50)"

    if texto is not None:
        msg.set_content(texto)
    if html is not None:
        if texto is None:
            msg.set_content("", subtype="plain")
            msg.clear_content()
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")
    for nome_anexo, dados in (anexos or []):
        msg.add_attachment(dados, maintype="application",
                           subtype="octet-stream", filename=nome_anexo)

    caminho = pasta / nome
    caminho.write_bytes(msg.as_bytes())
    return caminho


# ------------------------------------------------------------------ 1 a 4


def test_1_texto_simples(tmp_path):
    p = escrever_eml(tmp_path, "a.eml", texto="Ola, esta e uma mensagem simples.")
    r = parse_eml(p)
    assert r.tipo_corpo == "plain"
    assert "mensagem simples" in r.texto
    assert r.n_anexos == 0
    assert r.parse_erro == ""


def test_2_multipart_texto_e_html(tmp_path):
    """Com as duas versoes, o texto/plain prevalece."""
    p = escrever_eml(
        tmp_path, "b.eml",
        texto="Versao em texto puro do aviso.",
        html="<html><body><p>Versao <b>HTML</b> do aviso.</p></body></html>",
    )
    r = parse_eml(p)
    assert r.tipo_corpo == "plain+html"
    assert "Versao em texto puro" in r.texto
    assert "<b>" not in r.texto and "HTML" not in r.texto


def test_3_somente_html_convertido(tmp_path):
    p = escrever_eml(
        tmp_path, "c.eml", texto=None,
        html="<html><head><style>p{color:red}</style></head>"
             "<body><p>Sua conta sera <b>bloqueada</b> hoje.</p>"
             "<script>alert(1)</script></body></html>",
    )
    r = parse_eml(p)
    assert r.tipo_corpo == "html"
    assert "Sua conta sera bloqueada hoje." in r.texto
    assert "<" not in r.texto          # marcacao removida
    assert "color:red" not in r.texto  # style descartado
    assert "alert" not in r.texto      # script descartado


def test_4_anexo_nao_entra_no_texto(tmp_path):
    p = escrever_eml(
        tmp_path, "d.eml", texto="Segue o boleto em anexo.",
        anexos=[("boleto.pdf", b"%PDF-1.4 conteudo binario do anexo")],
    )
    r = parse_eml(p)
    assert r.n_anexos == 1
    assert "Segue o boleto" in r.texto
    assert "PDF" not in r.texto
    assert "binario" not in r.texto


# ------------------------------------------------------------------ 5 e 6


def test_5_dados_pessoais_sao_mascarados(tmp_path):
    corpo = (
        "Prezado Joao Silva, confirmamos seu cadastro.\n"
        "CPF: 123.456.789-00\n"
        "Telefone: (11) 98765-4321\n"
        "E-mail: joao.silva@provedor.com.br\n"
        "Cartao: 4111 1111 1111 1111\n"
        "CEP: 13330-250\n"
    )
    p = escrever_eml(tmp_path, "e.eml", texto=corpo, para="Joao Silva <joao.silva@provedor.com.br>")
    r = parse_eml(p)

    # valores originais nao sobrevivem
    for valor in ("123.456.789-00", "98765-4321", "joao.silva@provedor.com.br",
                  "4111 1111 1111 1111", "13330-250", "Joao Silva"):
        assert valor not in r.texto, f"vazou: {valor}"

    # categorias ficam registradas
    cats = set(r.categorias_anonimizadas.split(","))
    assert {"cpf", "telefone", "email", "cartao"} <= cats
    # o valor original NUNCA e preservado em campo nenhum
    assert "123.456.789" not in str(r.__dict__)


def test_6_url_preserva_estrutura_e_mascara_parametro(tmp_path):
    corpo = ("Acesse https://portal.exemplo.com.br/area/cliente"
             "?id=AB93KDJ2LS0192KDLS&campanha=setembro")
    p = escrever_eml(tmp_path, "f.eml", texto=corpo)
    r = parse_eml(p)

    assert "portal.exemplo.com.br/area/cliente" in r.texto  # estrutura mantida
    assert "AB93KDJ2LS0192KDLS" not in r.texto              # valor mascarado
    assert "campanha=setembro" in r.texto                   # nao identificavel
    assert "url_param" in r.categorias_anonimizadas


# ------------------------------------------------------------------ 7 a 9


def test_7_mensagem_malformada_nao_derruba(tmp_path):
    p = tmp_path / "g.eml"
    p.write_bytes(b"\xff\xfe isto nao e um email valido \x00\x01 sem cabecalho")
    r = parse_eml(p)
    assert r.id.startswith("eml_")
    assert r.origem_ref  # rastreabilidade preservada mesmo no erro


def test_8_acentuacao_ptbr_preservada(tmp_path):
    corpo = "Atenção: sua inscrição não foi concluída. Regularize até terça-feira."
    p = escrever_eml(tmp_path, "h.eml", assunto="Notificação urgente", texto=corpo)
    r = parse_eml(p)
    assert "Atenção" in r.texto
    assert "inscrição não foi concluída" in r.texto
    assert "Notificação" in r.assunto


def test_9_duplicata_removida_no_lote(tmp_path):
    corpo = "Sua fatura esta disponivel para consulta."
    escrever_eml(tmp_path, "i1.eml", texto=corpo)
    escrever_eml(tmp_path, "i2.eml", texto=corpo.upper())  # difere so na caixa
    escrever_eml(tmp_path, "i3.eml", texto="Mensagem completamente diferente.")
    registros = processar_lote(tmp_path)
    assert len(registros) == 2, [r.texto[:30] for r in registros]


# ------------------------------------------------------------------ 10


def test_10_eml_original_nao_e_modificado(tmp_path):
    p = escrever_eml(tmp_path, "j.eml", texto="CPF 123.456.789-00 no corpo.")
    antes = hashlib.sha256(p.read_bytes()).hexdigest()
    mtime_antes = p.stat().st_mtime

    parse_eml(p)
    processar_lote(tmp_path)

    assert hashlib.sha256(p.read_bytes()).hexdigest() == antes
    assert p.stat().st_mtime == mtime_antes
    # o dado pessoal continua no bruto — e por isso raw_private nao e versionado
    assert b"123.456.789-00" in p.read_bytes()


# ------------------------------------------------- garantias transversais


def test_hash_usa_a_normalizacao_do_schema(tmp_path):
    p = escrever_eml(tmp_path, "k.eml", texto="Texto   com    espacos   irregulares.")
    r = parse_eml(p)
    assert r.hash == calcular_hash(r.texto)


def test_id_estavel_para_o_mesmo_arquivo(tmp_path):
    p = escrever_eml(tmp_path, "l.eml", texto="Conteudo fixo para id estavel.")
    assert parse_eml(p).id == parse_eml(p).id


def test_cabecalhos_sensiveis_nao_sao_copiados(tmp_path):
    p = escrever_eml(tmp_path, "m.eml", texto="Corpo qualquer.",
                     de="fraude@malicioso.tk", para="vitima@provedor.com")
    r = parse_eml(p)
    bruto = str(r.__dict__)
    for sensivel in ("192.168.1.50", "abc123@exemplo.com.br",
                     "vitima@provedor.com", "fraude@malicioso.tk"):
        assert sensivel not in bruto, f"cabecalho sensivel copiado: {sensivel}"
    # do remetente sobra apenas o hash do dominio
    assert len(r.remetente_dominio_hash) == 16


def test_campos_de_curadoria_ficam_vazios(tmp_path):
    """O parser nao decide rotulo, arquetipo, particao nem revisao."""
    p = escrever_eml(tmp_path, "n.eml",
                     texto="URGENTE: sua conta sera bloqueada, clique aqui!")
    r = parse_eml(p)
    assert r.rotulo == "" and r.arquetipo == "" and r.particao == ""
    assert r.revisado is False
    assert set(r.pendencias()) == set(PENDENTES_CURADORIA)


def test_rastreabilidade_sem_expor_caminho(tmp_path):
    p = escrever_eml(tmp_path, "segredo_caixa_do_pedro.eml", texto="Corpo.")
    r = parse_eml(p)
    assert r.origem_ref == hashlib.sha256(p.read_bytes()).hexdigest()
    assert "segredo_caixa_do_pedro" not in str(r.__dict__)
    assert str(tmp_path) not in str(r.__dict__)


def test_anonimizacao_nao_guarda_valor_original():
    res = anonimizar("Meu CPF e 123.456.789-00 e o telefone (11) 98765-4321.")
    assert "123.456.789-00" not in res.texto
    assert "123.456.789-00" not in str(res.ocorrencias)
    assert res.categorias == {"cpf", "telefone"}
    assert res.ocorrencias == {"cpf": 1, "telefone": 1}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
