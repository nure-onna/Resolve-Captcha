# Resolve-Captcha

Código Python com funções de OCR  para CAPTCHA e RECAPTCHA e interação com desafios de imagens usando Playwright, Tesseract e uma API de IA local compatível com OpenAI ou Gemini online.

## Estrutura

- `autenticacao.py`: funções de processamento de imagens e interação com a página.
- `requirements.txt`: dependências Python.
- `.gitignore`: exclusões de ambientes virtuais, arquivos temporários e configurações locais.

## Preparação

Requer Python 3.10 ou superior e Tesseract OCR instalado separadamente.

No PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
$env:LOCAL_AI_API_KEY = "sua-chave"
```

O caminho do Tesseract está configurado em `autenticacao.py` como
`C:\Program Files\Tesseract-OCR\tesseract.exe`. Ajuste conforme a instalação.

O endereço `base_url` no código é um placeholder e precisa ser substituído pelo
endereço do servidor de IA. O modelo padrão também precisa existir nesse servidor.

O arquivo contém funções para serem importadas por uma automação que forneça uma
página ou frame do Playwright; ele não possui um fluxo principal de execução.
A variável `LOCAL_AI_API_KEY` é exigida já na importação do módulo.
Arquivos `.env` não são carregados automaticamente.

## Versionamento

Não inclua chaves de API ou senhas no código. Configure-as por variáveis de ambiente.
As dependências ainda não têm versões fixadas; a execução precisa ser validada no
ambiente de destino.
