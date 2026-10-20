import re
import cv2
import numpy as np
import pytesseract
import base64
import time
import os
from PIL import Image
from io import BytesIO
from openai import OpenAI
from playwright.sync_api import Frame, Page

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# Configuração da chave da API de IA local ou Gemini-3.6-Flash (vLLM) para resolver desafios de CAPTCHA e reCAPTCHA.
chave_ia= os.environ.get("LOCAL_AI_API_KEY")

if not chave_ia:
    raise RuntimeError("Variável LOCAL_AI_API_KEY não configurada.")

client = OpenAI(
    base_url="http://00.00.00.00:0000/v1",
    api_key=chave_ia,
)

def ler_e_preencher_captcha(
    alvo: Frame | Page,
    seletor_imagem: str,
    seletor_input: str,
    timeout_ms: int,
) -> str:
    elemento_img = alvo.locator(seletor_imagem).first
    elemento_img.wait_for(state="visible", timeout=timeout_ms)

    screenshot_bytes = elemento_img.screenshot()

    nparr = np.frombuffer(screenshot_bytes, np.uint8)
    imagem = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)

    altura, largura = cinza.shape[:2]
    ampliada = cv2.resize(
        cinza, (largura * 2, altura * 2), interpolation=cv2.INTER_CUBIC
    )

    _, thresh = cv2.threshold(
        ampliada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    config_tesseract = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    numeros = pytesseract.image_to_string(thresh, config=config_tesseract).strip()

    numeros = "".join(filter(str.isdigit, numeros))

    print(f"[OCR] Texto reconhecido: '{numeros}'")

    if not numeros or len(numeros) != 4:
        print("[OCR] Aviso: O OCR não encontrou 4 dígitos limpos. Verifique a imagem.")

    campo = alvo.locator(seletor_input).first
    campo.wait_for(state="visible", timeout=timeout_ms)
    campo.fill("")

    for digito in numeros:
        campo.type(digito, delay=100)

    return numeros

def resolver_recaptcha_imagens(pagina: Page, nome_modelo_vllm: str = " modelo - de - sua - ia - aqui ") -> bool:
    for tentativa in range(5):
        try:
            frame_ancora = next((f for f in pagina.frames if "anchor" in f.url.lower()), None)
            if frame_ancora:
                marcado = frame_ancora.locator('#recaptcha-anchor[aria-checked="true"]')
                if marcado.count() > 0 and marcado.is_visible():
                    print("[RECAPTCHA] Check verde detectado! Finalizando resolução de imagens.")
                    return True
        except Exception:
            pass

        frame_desafio = None
        for _ in range(10):
            frame_desafio = next((f for f in pagina.frames if "bframe" in f.url.lower()), None)
            if frame_desafio and frame_desafio.locator("#rc-imageselect-target, table.rc-imageselect-table").count() > 0:
                break
            pagina.wait_for_timeout(1000)

        if not frame_desafio or frame_desafio.locator("#rc-imageselect-target, table.rc-imageselect-table").count() == 0:
            print("[RECAPTCHA] Desafio visual concluído com sucesso!")
            return True

        try:
            instrucao_elem = frame_desafio.locator(".rc-imageselect-instructions").inner_text()
            print(f"[RECAPTCHA] Instrução atual: {instrucao_elem}")
        except Exception:
            instrucao_elem = "identificar os objetos solicitados"

        container_grade = frame_desafio.locator("#rc-imageselect-target, table.rc-imageselect-table").first

        for rodada_dinamica in range(4):
            try:
                container_grade.wait_for(state="visible", timeout=5_000)
                pagina.wait_for_timeout(1200)
                screenshot_bytes = container_grade.screenshot()
                img_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            except Exception as e:
                print(f"[RECAPTCHA] Grade fechou ou sumiu durante o print: {e}")
                return True

            prompt = (
                f"Esta é uma grade de um desafio reCAPTCHA do Google. A instrução exata é: '{instrucao_elem}'. "
                "A grade pode ser 3x3 (9 quadradinhos) ou 4x4 (16 quadradinhos). "
                "O objeto solicitado SEMPRE aparece em alguns dos quadradinhos desta imagem. "
                "Analise detalhadamente cada quadradinho da grade e liste rigorosamente todas as coordenadas (Linha e Coluna, começando do 1) "
                "que contenham qualquer parte do objeto pedido. "
                "Se não houver nenhum objeto pedido visível na imagem, responda apenas: 'nenhum'. "
                "Responda estritamente no formato de lista de coordenadas, por exemplo: Linha 1 Coluna 1, Linha 2 Coluna 1."
            )

            try:
                resposta = client.chat.completions.create(
                    model=nome_modelo_vllm,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
                        ]
                    }]
                )
                texto_resposta = resposta.choices[0].message.content.strip()
                print(f"[RECAPTCHA IA LOCAL] Rodada {rodada_dinamica + 1} - Resposta: {texto_resposta}")
            except Exception as e:
                print(f"[RECAPTCHA] Erro na chamada do vLLM: {e}")
                return False

            if "nenhum" in texto_resposta.lower():
                print("[RECAPTCHA] Nenhum novo objeto detectado. Pronto para confirmar.")
                break

            tiles = frame_desafio.locator("td.rc-imageselect-tile")
            total_tiles = tiles.count()
            colunas = 4 if total_tiles == 16 else 3
            cliques_realizados = 0

            for i in range(total_tiles):
                linha_atual = (i // colunas) + 1
                coluna_atual = (i % colunas) + 1

                termo_busca = f"linha {linha_atual} coluna {coluna_atual}"
                if termo_busca in texto_resposta.lower():
                    tile = tiles.nth(i)
                    classes = tile.evaluate("el => el.className")

                    if "rc-imageselect-tileselected" in classes:
                        print(f"[RECAPTCHA] Ignorado (já selecionado) -> Linha {linha_atual}, Coluna {coluna_atual}")
                        continue

                    print(f"[RECAPTCHA] Clicando -> Linha {linha_atual}, Coluna {coluna_atual}")
                    tile.click()
                    cliques_realizados += 1
                    pagina.wait_for_timeout(800)

            if cliques_realizados > 0:
                print("[RECAPTCHA] Aguardando substituição total das imagens dinâmicas...")
                pagina.wait_for_timeout(4000)
            else:
                break

        try:
            botao_acao = frame_desafio.locator("#recaptcha-verify-button")
            if botao_acao.count() > 0:
                print("[RECAPTCHA] Clicando no botão de verificação...")
                botao_acao.click()
                pagina.wait_for_timeout(3500)
        except Exception:
            pass

    print("[RECAPTCHA] Limite de tentativas do desafio atingido.")
    return False





#CÓDIGO COMPLETO E FUNCIONAL RESOLVER CAPTCHA COM PLAYWRIGHT, TESSERACT E GEMINI-3.6-FLASH (IA) - 2024 só conectar API KEY da sua IA local ou Gemini-3.6-Flash (vLLM) na variável de ambiente LOCAL_AI_API_KEY

#import re
#import cv2
#import numpy as np
#import pytesseract
#from playwright.sync_api import Frame, Page
#
#import time
#from PIL import Image
#from io import BytesIO
#import google.generativeai as genai
#from playwright.sync_api import Page
#
#
#pytesseract.pytesseract.tesseract_cmd = (
#    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
#)
#
#def ler_e_preencher_captcha(
#    alvo: Frame | Page,
#    seletor_imagem: str,
#    seletor_input: str,
#    timeout_ms: int,
#) -> str:
#    while True:
#        elemento_img = alvo.locator(seletor_imagem).first
#        elemento_img.wait_for(state="visible", timeout=timeout_ms)
#
#        screenshot_bytes = elemento_img.screenshot()
#
#        nparr = np.frombuffer(screenshot_bytes, np.uint8)
#        imagem = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
#
#        cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
#
#        altura, largura = cinza.shape[:2]
#        ampliada = cv2.resize(
#            cinza, (largura * 2, altura * 2), interpolation=cv2.INTER_CUBIC
#        )
#
#        _, thresh = cv2.threshold(
#            ampliada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
#        )
#
#        config_tesseract = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
#        numeros = pytesseract.image_to_string(thresh, config=config_tesseract).strip()
#        numeros = "".join(filter(str.isdigit, numeros))
#
#        print(f"[OCR] Texto reconhecido: '{numeros}'")
#
#        if not numeros or len(numeros) != 4:
#            print(
#                "[OCR] Aviso: O OCR não encontrou 4 dígitos limpos. Clicando em retornar para tentar novamente..."
#            )
#            try:
#                botao_retornar = alvo.locator("img.bt_atualizar, a.atualizar_captcha, div.btn-voltar, text='Retornar', text='Voltar'").first
#                if botao_retornar.count() > 0:
#                    botao_retornar.click()
#                else:
#                    elemento_img.click()
#                alvo.wait_for_timeout(2000)
#                continue
#            except Exception as e:
#                print(f"[OCR] Erro ao tentar acionar o botão de retornar: {e}")
#
#        campo = alvo.locator(seletor_input).first
#        campo.wait_for(state="visible", timeout=timeout_ms)
#        campo.fill("")
#
#        for digito in numeros:
#            campo.type(digito, delay=100)
#
#        return numeros
#
#def resolver_recaptcha_imagens(pagina: Page) -> bool:
#    """
#    Resolve o reCAPTCHA de imagens e sai do loop assim que o desafio some
#    ou o check verde é atingido com sucesso.
#    """
#    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
#    model = genai.GenerativeModel('gemini-3.6-flash')
#
#    for tentativa in range(5):
#        try:
#            frame_ancora = next((f for f in pagina.frames if "anchor" in f.url.lower()), None)
#            if frame_ancora:
#                marcado = frame_ancora.locator('#recaptcha-anchor[aria-checked="true"]')
#                if marcado.count() > 0 and marcado.is_visible():
#                    print("[RECAPTCHA] Check verde detectado! Finalizando resolução de imagens.")
#                    return True
#        except Exception:
#            pass
#
#        frame_desafio = None
#        for _ in range(10):
#            frame_desafio = next((f for f in pagina.frames if "bframe" in f.url.lower()), None)
#            if frame_desafio and frame_desafio.locator("#rc-imageselect-target, table.rc-imageselect-table").count() > 0:
#                break
#            pagina.wait_for_timeout(1000)
#
#        if not frame_desafio or frame_desafio.locator("#rc-imageselect-target, table.rc-imageselect-table").count() == 0:
#            print("[RECAPTCHA] Desafio visual concluído com sucesso!")
#            return True
#
#        try:
#            instrucao_elem = frame_desafio.locator(".rc-imageselect-instructions").inner_text()
#            print(f"[RECAPTCHA] Instrução atual: {instrucao_elem}")
#        except Exception:
#            instrucao_elem = "identificar os objetos solicitados"
#
#        container_grade = frame_desafio.locator("#rc-imageselect-target, table.rc-imageselect-table").first
#        try:
#            container_grade.wait_for(state="visible", timeout=5_000)
#            pagina.wait_for_timeout(1200)
#            screenshot_bytes = container_grade.screenshot()
#            imagem_pil = Image.open(BytesIO(screenshot_bytes))
#        except Exception as e:
#            print(f"[RECAPTCHA] Grade fechou ou sumiu durante o print: {e}")
#            return True
#
#        prompt = (
#            f"Esta é uma grade de um desafio reCAPTCHA do Google. A instrução exata é: '{instrucao_elem}'. "
#            "A grade pode ser 3x3 (9 quadradinhos) ou 4x4 (16 quadradinhos). "
#            "O objeto solicitado SEMPRE aparece em alguns dos quadradinhos desta imagem. "
#            "Analise detalhadamente cada quadradinho da grade e liste rigorosamente todas as coordenadas (Linha e Coluna, começando do 1) "
#            "que contenham qualquer parte do objeto pedido. "
#            "Responda estritamente no formato de lista de coordenadas, por exemplo: Linha 1 Coluna 1, Linha 2 Coluna 1."
#        )
#
#        try:
#            resposta = model.generate_content([prompt, imagem_pil])
#            texto_resposta = resposta.text.strip()
#            print(f"[RECAPTCHA IA] Resposta: {texto_resposta}")
#        except Exception as e:
#            print(f"[RECAPTCHA] Erro na chamada do Gemini: {e}")
#            break
#
#        if "nenhum" not in texto_resposta.lower():
#            tiles = frame_desafio.locator("td.rc-imageselect-tile")
#            total_tiles = tiles.count()
#            colunas = 4 if total_tiles == 16 else 3
#
#            for i in range(total_tiles):
#                linha_atual = (i // colunas) + 1
#                coluna_atual = (i % colunas) + 1
#
#                termo_busca = f"linha {linha_atual} coluna {coluna_atual}"
#                if termo_busca in texto_resposta.lower():
#                    print(f"[RECAPTCHA] Clicando -> Linha {linha_atual}, Coluna {coluna_atual}")
#                    tiles.nth(i).click()
#                    pagina.wait_for_timeout(800)
#
#        pagina.wait_for_timeout(1200)
#
#        try:
#            botao_acao = frame_desafio.locator("#recaptcha-verify-button")
#            if botao_acao.count() > 0:
#                print("[RECAPTCHA] Clicando no botão de verificação...")
#                botao_acao.click()
#                pagina.wait_for_timeout(3500)
#        except Exception:
#            pass
#
#    print("[RECAPTCHA] Limite de tentativas do desafio atingido.")
#    return False
