# NewsSearch

Servidor local que agrega RSS de fontes brasileiras e internacionais
relevantes para consultoria em desenvolvimento de lideranças, cultura
organizacional e times. Faz curadoria automática com filtros por eixo
temático (liderança, cultura, engajamento, RH, futuro do trabalho, nova
geração, saúde mental, IA no trabalho, conflitos com repercussão e setor
do cliente: turismo, hotelaria, parques, agronegócio).

## Como rodar

Requer apenas Python 3 (sem dependências externas).

```bash
python3 server.py
```

Abre em [http://127.0.0.1:8765](http://127.0.0.1:8765).

## Como parar

```bash
kill $(lsof -ti tcp:8765)
```

## Estrutura

- `server.py` — agregador RSS, scoring por palavra-chave com fronteiras
  de palavra, filtro por temas core obrigatórios, denylist para ruído.
- `index.html` — frontend em Tailwind via CDN, layout escuro, card
  destacado de "Recomendação do dia" e botão para copiar briefing pronto
  no formato A–H.
