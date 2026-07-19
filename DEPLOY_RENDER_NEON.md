# Publicação gratuita: GitHub + Render + Neon

## 1. Preparar o repositório no GitHub

1. Crie um repositório vazio chamado `sistema-gestao-animais`.
2. Envie o conteúdo desta pasta para a raiz do repositório.
3. Confirme que `.env`, `.venv` e `data/sistema_animais.db` não foram enviados. O arquivo `.gitignore` já bloqueia esses itens.

## 2. Criar o banco no Neon

1. Crie um projeto PostgreSQL no Neon.
2. No painel do projeto, use **Connect**.
3. Copie a conexão com pooling habilitado. Ela normalmente contém `-pooler` no endereço e `sslmode=require`.
4. Guarde essa conexão. Ela será cadastrada como `DATABASE_URL` no Render.

## 3. Criar o serviço no Render

### Método recomendado: Blueprint

1. No Render, escolha **New > Blueprint**.
2. Conecte o repositório do GitHub.
3. O Render localizará o arquivo `render.yaml`.
4. Preencha as variáveis solicitadas:
   - `DATABASE_URL`: conexão copiada do Neon;
   - `ADMIN_USERNAME`: usuário administrador, em letras minúsculas;
   - `ADMIN_PASSWORD`: senha forte com pelo menos 10 caracteres.
5. Confirme a criação do serviço.

O `render.yaml` já define instalação, inicialização, HTTPS no cookie e verificação em `/health`. As migrações do banco são aplicadas automaticamente pelo Alembic antes da aplicação aceitar acessos.

### Configuração manual, caso não use Blueprint

- Build command: `python -m pip install --upgrade pip && pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`
- Health check path: `/health`

Cadastre também:

- `APP_ENV=production`
- `DATABASE_URL=<conexão do Neon>`
- `SECRET_KEY=<sequência aleatória com pelo menos 32 caracteres>`
- `ADMIN_USERNAME=<usuário>`
- `ADMIN_PASSWORD=<senha forte>`
- `COOKIE_SECURE=true`
- `SESSION_MAX_AGE=28800`
- `RESET_ADMIN_PASSWORD=false`

## 4. Migrar os dados locais

A migração é feita do seu computador diretamente para o Neon.

1. Feche o sistema local.
2. Copie o banco anterior para `data/sistema_animais.db` desta versão.
3. Abra o terminal dentro desta pasta.
4. Ative o ambiente virtual:

```bat
.venv\Scripts\activate
```

5. Defina temporariamente a conexão do Neon no terminal do Windows:

```bat
set DATABASE_URL=postgresql://USUARIO:SENHA@SERVIDOR/BASE?sslmode=require
```

6. Valide sem gravar:

```bat
python scripts\migrate_sqlite_to_postgres.py --dry-run
```

7. Execute a migração:

```bat
python scripts\migrate_sqlite_to_postgres.py
```

Por segurança, o script interrompe a operação quando o destino já contém animais ou produções. O parâmetro `--replace` apaga esses registros e só deve ser usado depois de confirmar um backup.

## 5. Conferir

1. Abra a URL `onrender.com` fornecida pelo Render.
2. Entre com `ADMIN_USERNAME` e `ADMIN_PASSWORD`.
3. Compare no painel:
   - quantidade de animais;
   - quantidade e valores de produção;
   - gráficos mensais;
   - registros mais recentes.

## Redefinir a senha administrativa

1. Defina uma nova `ADMIN_PASSWORD` no Render.
2. Altere `RESET_ADMIN_PASSWORD` para `true`.
3. Faça um novo deploy.
4. Após conseguir entrar, retorne `RESET_ADMIN_PASSWORD` para `false` e faça outro deploy.

## Atualizações futuras

Depois da ligação com o GitHub, alterações enviadas ao branch conectado podem gerar uma nova implantação automática. O banco permanece no Neon e não deve ser enviado dentro do repositório.
