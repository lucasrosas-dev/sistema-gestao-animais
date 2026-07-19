# Sistema de Gestão de Animais — versão 1.0.0

Aplicação web para gestão de animais, produção e resultados financeiros, construída com FastAPI, SQLAlchemy, Jinja2 e Alembic.

## Recursos

- painel gerencial com indicadores e gráficos;
- cadastro, genealogia, eventos e movimentações de animais;
- controle de produção com filtros, edição e paginação;
- custos, receitas, apropriações e rateios;
- resultado financeiro por competência e caixa;
- relatórios e exportações em CSV, Excel e PDF;
- usuários com perfis Administrador, Operador e Consulta;
- auditoria, CSRF, sessões seguras e proteção de login;
- verificações de saúde em `/health` e `/ready`;
- migrations incrementais com Alembic.

## Uso local no Windows

1. Execute `INICIAR_SISTEMA.bat`.
2. Aguarde o navegador abrir em `http://127.0.0.1:8000`.

Primeiro acesso local:

```text
Usuário: admin
Senha: admin12345
```

O sistema solicitará a troca da senha inicial.

## Dependências

- `requirements-local.txt`: execução local com SQLite;
- `requirements.txt`: execução online com PostgreSQL;
- `requirements-dev.txt`: testes automatizados.

## Testes

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

## Publicação

O ambiente online usa Render e PostgreSQL no Neon. Consulte [DEPLOY_RENDER_NEON.md](DEPLOY_RENDER_NEON.md).

O projeto não inclui banco de dados local, arquivo `.env`, senhas, tokens ou string de conexão.
