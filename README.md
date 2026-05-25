# NewsSearch

Agregador de RSS para curadoria em consultoria de desenvolvimento de
lideranças, cultura organizacional e times. Faz scoring por palavra-chave
com fronteiras de palavra, filtro por temas core obrigatórios e denylist
para descartar ruído. Foco em clientes de turismo, hotelaria, parques e
agronegócio.

## Como rodar

Duas formas, sem dependências externas além do Python stdlib.

### Local (interativo, regenera a cada request)

```bash
python3 server.py
```

Abre em [http://127.0.0.1:8765](http://127.0.0.1:8765). Cada clique em
"Atualizar" refaz as requisições aos feeds.

### Estático (GitHub Pages, serverless)

```bash
python3 server.py --build
```

Gera `news.json` no diretório do projeto. O `index.html` lê esse arquivo
direto, então basta servir os dois (mais a página) como conteúdo estático
em qualquer host.

## Deploy no GitHub Pages

Custo: **R$ 0** para repositório público.

1. No repositório, vá em **Settings → Pages** e escolha "GitHub Actions"
   como source.
2. O workflow [`.github/workflows/build-news.yml`](.github/workflows/build-news.yml)
   roda automaticamente:
   - A cada 1 hora (cron).
   - Sempre que você faz push em `main` e mexe em `server.py` ou no
     próprio workflow.
   - Manualmente via aba **Actions → Build news.json → Run workflow**.
3. O workflow gera `news.json`, comita no repo se mudou, e publica o site
   no Pages.

O frontend tenta carregar `news.json` primeiro; se não achar (rodando
local sem o arquivo gerado), cai pro endpoint `/api/news` do servidor
Python. Mesmo `index.html` serve os dois modos.

## Como parar o servidor local

```bash
kill $(lsof -ti tcp:8765)
```

No Windows: `Ctrl+C` no terminal onde o servidor está rodando.

## Estrutura

- `server.py` — agregador RSS, scoring por palavra-chave com fronteiras
  de palavra, filtro por temas core obrigatórios, denylist para ruído.
  Roda como servidor HTTP (modo padrão) ou gera `news.json` (`--build`).
- `index.html` — frontend em Tailwind via CDN. Layout escuro, card
  destacado de "Recomendação do dia" e botão para copiar briefing pronto
  no formato A–H.
- `news.json` — JSON gerado pelo workflow do Actions, lido pelo frontend
  em produção.
- `.github/workflows/build-news.yml` — agendador do rebuild e deploy
  para o GitHub Pages.
